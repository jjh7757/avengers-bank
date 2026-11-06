"""허브 정산 run 대사와 장부 정리 (ClearingHub SPEC 10.6, 실제 금융망 13단계 "은행 장부 정리").

허브는 하루치 타행 거래를 정산 run 하나로 묶어 은행별 차액(받을 돈 − 줄 돈)을 계산하고, 확정(SETTLED)하면
그만큼 각 은행의 모의 예치금을 옮긴다 (SPEC 10.3). 우리는 그 run의 거래 목록(대사 파일)을 우리 장부와
transfer_id 하나하나로 맞춰 보고, 확정된 run이 맞으면 정산 계정에 쌓인 그 run의 몫을 예치금 계정으로 옮긴다.

1. GET /v1/settlements (10.4) → 아직 끝나지 않은 run을 run_id 작은 것부터
     끝나지 않음 = 대사 행이 없음 / MATCHED가 아님 / MATCHED인데 장부를 아직 정리하지 않음(DRAFT 때 맞춰 봄)
     목록에서 빠진 끝나지 않은 run(취소됐거나 30일 지남)도 상세로 다시 본다
2. run마다 GET /v1/settlements/{run_id} (10.5) → reconcile_run
     CANCELLED → 무시. DRAFT 때 남긴 행은 지운다 (그 거래는 다음 run에 다시 나온다)
     DRAFT     → 비교만
     SETTLED   → 비교, 일치하면 같은 트랜잭션에서 SETTLE 분개
3. 비교. 우리 쪽 후보 = 정산 계정의 COMPLETE(+, SENT)·RECEIVE(−, RECEIVED) 줄 중 아직 어느 run에도 묶이지 않은 것
   (날짜로 자르지 않는다. 다시 볼 때를 위해 이 run에 이미 묶인 줄도 넣는다)
     허브 거래가 후보에 있고 방향·금액·상대 은행이 같음      → 일치
     후보에 없지만 우리 interbank_transfers에서 PENDING      → 확인 중 (CHECKING). 결과를 확인(3.4)한 뒤 다시 본다
     후보에 없음, 또는 방향·금액·상대 은행이 다름           → 불일치 (MISMATCH, hub_only / differs)
     후보에만 있음                                           → 불일치가 아니다. 다음 run으로 넘긴다
                                                               (cutoff_at − 1시간보다 먼저 끝났으면 ours_only_stale로 알림)
   일치한 것만으로 계산한 순액(받을 돈 − 줄 돈)이 허브 position.net_amount와 같아야 MATCHED
4. 장부 정리 (MATCHED이고 SETTLED이고 아직 안 했을 때 한 번): 상대 은행마다 n = 그 run에서 그 은행에 줄 돈
   (보낸 합 − 받은 합, 받을 돈이면 음수)에 대해 SETTLE 분개 "settle:{run_id}:{은행}"
     INTERBANK_SETTLEMENT:{은행} −n  (그만큼 갚았다 / 받았다)
     HUB_RESERVE                −n  (허브 예치금이 그만큼 줄었다 / 늘었다)
   → HUB_RESERVE 변화 = Σ(−n) = 허브 position.net_amount. 맞춘 분개에 hub_run_id를 찍어 다음 대사에서 다시 세지 않는다
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.clock import now_utc
from avengers_bank.domains.interbank.hub_client import hub_client
from avengers_bank.domains.interbank.models import (
    InterbankLedgerEntry,
    InterbankStatus,
    InterbankTransfer,
    LedgerAccount,
    LedgerEvent,
    ReconResult,
    SettlementReconciliation,
)
from avengers_bank.domains.interbank.service import _post, confirm_pending

logger = logging.getLogger(__name__)

# SPEC 10.6 "내 쪽에만 있는 거래": cutoff_at보다 이만큼 먼저 끝났는데도 허브 run에 없으면 허브 관리자에게 알린다
STALE_AFTER = timedelta(hours=1)
SENT, RECEIVED = "SENT", "RECEIVED"
_MATCHABLE = (LedgerEvent.COMPLETE, LedgerEvent.RECEIVE)


@dataclass(frozen=True)
class _Line:
    """우리 장부의 대사 후보 한 건 (정산 계정 줄)."""

    direction: str  # SENT / RECEIVED (우리 기준)
    counterparty_bank: str
    amount: int  # 양수
    created_at: datetime

    def view(self) -> dict:
        return {"direction": self.direction, "counterparty_bank": self.counterparty_bank, "amount": self.amount}


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)  # SQLite는 시간대 없이 돌려준다


def _unfinished(row: SettlementReconciliation | None) -> bool:
    return row is None or row.result != ReconResult.MATCHED or row.settled_at is None


async def _candidates(db: AsyncSession, run_id: int) -> dict[str, _Line]:
    entry = InterbankLedgerEntry
    rows = await db.scalars(
        select(entry).where(entry.account == LedgerAccount.SETTLEMENT, entry.event.in_(_MATCHABLE),
                            or_(entry.hub_run_id.is_(None), entry.hub_run_id == run_id))
    )
    return {
        e.transfer_id: _Line(SENT if e.event == LedgerEvent.COMPLETE else RECEIVED, e.bank_code, abs(e.amount),
                             e.created_at)
        for e in rows
    }


async def _hub_only(db: AsyncSession, transfer_id: str, hub: dict) -> dict:
    """허브에만 있는 거래. 다른 run에서 이미 맞춘 거래가 또 나왔으면 그 run을 함께 적는다."""
    item = {"transfer_id": transfer_id, **hub}
    settled_in = await db.scalar(
        select(InterbankLedgerEntry.hub_run_id)
        .where(InterbankLedgerEntry.transfer_id == transfer_id, InterbankLedgerEntry.hub_run_id.is_not(None)).limit(1)
    )
    if settled_in is not None:
        item["settled_in"] = settled_in
    return item


async def _settle(db: AsyncSession, run_id: int, matched: dict[str, _Line]) -> None:
    """SPEC 10.6의 4: 맞춘 분개에 run을 찍고, 상대 은행별 몫을 정산 계정 → 예치금 계정으로 옮긴다.
    transfer_id "settle:{run_id}:{은행}"이 분개 유니크 제약에 걸려 같은 run을 두 번 정리할 수 없다."""
    entry = InterbankLedgerEntry
    if matched:
        stamped = await db.execute(
            update(entry)
            .where(entry.transfer_id.in_(list(matched)), entry.account == LedgerAccount.SETTLEMENT,
                   entry.event.in_(_MATCHABLE), entry.hub_run_id.is_(None))
            .values(hub_run_id=run_id).execution_options(synchronize_session=False)
        )
        if stamped.rowcount != len(matched):  # 그사이 다른 대사가 찍었다: 롤백하고 다음 주기에 다시
            raise RuntimeError(f"정산 run {run_id}: 맞춘 분개 {len(matched)}건 중 {stamped.rowcount}건만 표시됨")
    owed: dict[str, int] = defaultdict(int)  # 상대 은행별 그 run에서 우리가 줄 돈 (받을 돈이면 음수)
    for line in matched.values():
        owed[line.counterparty_bank] += line.amount if line.direction == SENT else -line.amount
    for bank, net in sorted(owed.items()):
        if net:  # 주고받은 것이 같으면 옮길 돈이 없다 (맞춘 분개의 표시만 남는다)
            _post(db, f"settle:{run_id}:{bank}", LedgerEvent.SETTLE, bank,
                  (LedgerAccount.SETTLEMENT, -net), (LedgerAccount.HUB_RESERVE, -net), hub_run_id=run_id)


async def reconcile_run(db: AsyncSession, detail: dict) -> SettlementReconciliation | None:
    """허브 대사 파일(SPEC 10.5 응답) 하나를 우리 장부와 맞춘다 (한 트랜잭션). CANCELLED면 None.
    같은 run을 다시 부르면 행을 갱신하고, 장부 정리(SETTLE 분개)는 run마다 한 번만 한다."""
    run_id, status = int(detail["run_id"]), str(detail["status"])
    async with db.begin():
        row = await db.get(SettlementReconciliation, run_id, with_for_update=True)
        if status == "CANCELLED":
            if row is not None and row.settled_at is None:
                await db.delete(row)  # DRAFT 때 맞춰 본 기록. 그 거래는 다음 run에 다시 나온다
            elif row is not None:
                logger.error("정산 run %d: 장부를 정리한 run이 허브에서 CANCELLED로 나옴 (허브 관리자 확인 필요)", run_id)
            return None

        candidates = await _candidates(db, run_id)
        hub_transfers: list[dict] = detail["transfers"]
        matched: dict[str, _Line] = {}
        hub_only: list[dict] = []
        differs: list[dict] = []
        checking: list[str] = []
        for t in hub_transfers:
            tid = str(t["transfer_id"])
            hub = {"direction": t["direction"], "counterparty_bank": t["counterparty_bank"], "amount": int(t["amount"])}
            ours = candidates.get(tid)
            if ours is not None:
                if ours.view() == hub:
                    matched[tid] = ours
                else:
                    differs.append({"transfer_id": tid, "hub": hub, "ours": ours.view()})
                continue
            our_status = await db.scalar(select(InterbankTransfer.status).where(InterbankTransfer.transfer_id == tid))
            if hub["direction"] == SENT and our_status == InterbankStatus.PENDING:
                checking.append(tid)  # 허브는 COMPLETED인데 우리가 결과를 아직 못 받았다
            else:
                hub_only.append(await _hub_only(db, tid, hub))

        listed = {str(t["transfer_id"]) for t in hub_transfers}
        ours_only = sorted(candidates.keys() - listed)
        stale_before = _as_utc(datetime.fromisoformat(detail["cutoff_at"])) - STALE_AFTER
        ours_only_stale = [tid for tid in ours_only if _as_utc(candidates[tid].created_at) < stale_before]

        hub_net = int(detail["position"]["net_amount"])
        our_net = sum(line.amount if line.direction == RECEIVED else -line.amount for line in matched.values())
        diff: dict = {"hub_only": hub_only, "differs": differs, "checking": checking,
                      "ours_only": ours_only, "ours_only_stale": ours_only_stale}
        if hub_only or differs:
            result = ReconResult.MISMATCH
        elif checking:
            result = ReconResult.CHECKING
        elif our_net != hub_net:
            result = ReconResult.MISMATCH
            diff["net"] = {"hub": hub_net, "ours": our_net}
        else:
            result = ReconResult.MATCHED

        now = now_utc()
        if row is None:
            row = SettlementReconciliation(hub_run_id=run_id)
            db.add(row)
        row.settle_date = date.fromisoformat(str(detail["settle_date"]))
        row.hub_status, row.hub_net_amount, row.our_net_amount = status, hub_net, our_net
        row.result = result
        row.diff_json = json.dumps({k: v for k, v in diff.items() if v}, ensure_ascii=False)
        row.checked_at = now
        settle_now = result == ReconResult.MATCHED and status == "SETTLED" and row.settled_at is None
        if settle_now:
            await _settle(db, run_id, matched)
            row.settled_at = now

    if result == ReconResult.MISMATCH:  # 자동 처리를 멈춘다. 허브 관리자에게 run_id와 차이 나는 transfer_id를 알린다
        logger.error("정산 run %d 대사 불일치: %s", run_id, row.diff_json)
    elif result == ReconResult.CHECKING:
        logger.info("정산 run %d 확인 중: 우리 쪽 PENDING %s", run_id, ", ".join(checking))
    if ours_only_stale:
        logger.warning("정산 run %d: cutoff보다 1시간 넘게 먼저 끝났는데 허브 run에 없는 거래 %s (허브 관리자 확인 필요)",
                       run_id, ", ".join(ours_only_stale))
    if settle_now:
        logger.info("정산 run %d 장부 정리: 허브 예치금 %+d원 (거래 %d건)", run_id, hub_net, len(matched))
    return row


async def sync_settlements(db: AsyncSession) -> list[SettlementReconciliation]:
    """허브 정산 목록에서 끝나지 않은 run을 run_id 오름차순으로 맞춰 본다 (SPEC 10.6의 1·2·5, 워커가 주기적으로 부른다).
    처리한 run의 대사 행을 돌려준다. 허브가 응답하지 않거나 거절하면 기록만 하고 빈 목록 (다음 주기에 다시)."""
    reply = await hub_client.settlements()
    if not reply.ok:
        logger.warning("허브 정산 목록을 받지 못함: %s %s (다음 주기에 다시)", reply.status, reply.error)
        return []
    listed = {int(s["run_id"]) for s in reply.body.get("settlements", []) if isinstance(s, dict) and "run_id" in s}
    recon = SettlementReconciliation
    async with db.begin():
        known = {
            r.hub_run_id: r for r in await db.scalars(
                select(recon).where(or_(recon.hub_run_id.in_(listed), recon.result != ReconResult.MATCHED,
                                        recon.settled_at.is_(None)))
            )
        }
    todo = sorted(run_id for run_id in listed | known.keys() if _unfinished(known.get(run_id)))

    done: list[SettlementReconciliation] = []
    for run_id in todo:
        detail = await hub_client.settlement(run_id)
        if detail.status == 404:
            logger.warning("정산 run %d를 허브가 모름 (%s). 건너뜀", run_id, detail.error)
            continue
        if not detail.ok:
            logger.warning("정산 run %d 대사 파일을 받지 못함: %s %s (다음 주기에 다시)", run_id, detail.status, detail.error)
            break
        try:
            row = await reconcile_run(db, detail.body)
            # 확인 중: 허브에 결과를 물어(3.4) PENDING을 마무리한 뒤 한 번 더 맞춰 본다
            if row is not None and row.result == ReconResult.CHECKING and await confirm_pending(db):
                row = await reconcile_run(db, detail.body)
        except Exception:  # 한 run이 실패해도 다른 run의 대사는 계속한다 (SPEC 10.6)
            logger.exception("정산 run %d 대사 실패", run_id)
            continue
        if row is not None:
            done.append(row)
    return done
