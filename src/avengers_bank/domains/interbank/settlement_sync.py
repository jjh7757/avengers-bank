"""허브 정산 run 대사와 장부 정리 (ClearingHub SPEC 10.6, 실제 금융망 13단계 "은행 장부 정리").

허브는 하루치 타행 거래를 정산 run 하나로 묶어 은행별 차액(받을 돈 − 줄 돈)을 계산하고, 확정(SETTLED)하면
그만큼 각 은행의 모의 예치금을 옮긴다 (SPEC 10.3). 우리는 그 run의 거래 목록(대사 파일)을 우리 장부와
transfer_id 하나하나로 맞춰 보고, 확정된 run이 맞으면 정산 계정에 쌓인 그 run의 몫을 예치금 계정으로 옮긴다.

1. GET /v1/settlements (10.4) → 아직 끝나지 않은 run을 run_id 작은 것부터
     끝나지 않음 = 대사 행이 없음 / MATCHED가 아님 / MATCHED인데 장부를 아직 정리하지 않음(DRAFT 때 맞춰 봄)
     목록에서 빠진 끝나지 않은 run(취소됐거나 30일 지남)도 상세로 다시 본다
2. run마다 GET /v1/settlements/{run_id} (10.5) → reconcile_run
     CANCELLED → 무시. DRAFT 때 남긴 행은 지운다 (그 거래는 다음 run에 다시 나온다)
     DRAFT     → 비교하고 결과를 허브에 보낸다 (10.8, 아래 5)
     SETTLED   → 비교, 일치하면 같은 트랜잭션에서 SETTLE 분개
3. 비교. 우리 쪽 후보 = 정산 계정의 COMPLETE(+, SENT)·RECEIVE(−, RECEIVED) 줄 중 아직 어느 run에도 묶이지 않은 것
   (날짜로 자르지 않는다. 다시 볼 때를 위해 이 run에 이미 묶인 줄도 넣는다)
     허브 거래가 후보에 있고 방향·금액·상대 은행이 같음      → 일치
     후보에 없지만 우리 interbank_transfers에서 PENDING (보낸 거래)
       run이 DRAFT                                           → 확인 중 (CHECKING). 결과를 확인(3.4)한 뒤 다시 본다
       run이 SETTLED이고 상대 은행·금액이 우리 기록과 같음   → 완료로 확정하고 일치로 센다 (resolved_by_settlement)
         허브가 그 거래를 정산에 넣어 예치금까지 옮겼으므로, 실시간 결과를 끝내 못 받아도 이것이 완료의 근거다.
         DRAFT는 취소될 수 있어 근거로 쓰지 않는다
       run이 SETTLED인데 상대 은행·금액이 다름               → 불일치 (differs). 확정하지 않고 PENDING으로 둔다
     후보에 없음, 또는 방향·금액·상대 은행이 다름           → 불일치 (MISMATCH, hub_only / differs)
     후보에만 있음                                           → 불일치가 아니다. 다음 run으로 넘긴다
                                                               (cutoff_at − 1시간보다 먼저 끝났으면 ours_only_stale로 알림)
   일치한 것만으로 계산한 순액(받을 돈 − 줄 돈)이 허브 position.net_amount와 같아야 MATCHED
4. 장부 정리 (MATCHED이고 SETTLED이고 아직 안 했을 때 한 번): 상대 은행마다 n = 그 run에서 그 은행에 줄 돈
   (보낸 합 − 받은 합, 받을 돈이면 음수)에 대해 SETTLE 분개 "settle:{run_id}:{은행}"
     INTERBANK_SETTLEMENT:{은행} −n  (그만큼 갚았다 / 받았다)
     HUB_RESERVE                −n  (허브 예치금이 그만큼 줄었다 / 늘었다)
   → HUB_RESERVE 변화 = Σ(−n) = 허브 position.net_amount. 맞춘 분개에 hub_run_id를 찍어 다음 대사에서 다시 세지 않는다
5. 결과 보내기 (SPEC 10.8, DRAFT일 때만. 트랜잭션 밖에서 — 허브 호출 동안 행을 잠그지 않는다)
     MATCHED이고 지금 ack가 걸려 있지 않음     → POST ack, acked_at (disputed_at은 비운다)
     MISMATCH이고 지금 dispute가 걸려 있지 않음 → POST dispute {hub_only + differs의 transfer_id}, disputed_at
     CHECKING                                   → 보내지 않는다 (마무리한 뒤 다시 비교)
   ack 응답이 SETTLED(포지션이 있는 은행 전원 ack로 즉시 확정)거나 409 SETTLEMENT_NOT_DRAFT(그사이 확정·취소됨)면
   다음 주기를 기다리지 않고 상세를 다시 받아 한 번 더 맞춰 본다 → SETTLED면 그 자리에서 장부 정리까지 한다.
   보내지 못하면(응답 없음·5xx) 시각을 남기지 않아 다음 주기에 다시 보낸다. SETTLED에는 보내지 않는다 (허브가 409)
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
from avengers_bank.domains.interbank.service import _post, complete, confirm_pending

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
        resolved: list[str] = []  # 확정된 run을 근거로 PENDING에서 완료로 확정한 보낸 거래
        settled = status == "SETTLED"
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
            transfer = await db.scalar(
                select(InterbankTransfer).where(InterbankTransfer.transfer_id == tid).with_for_update()
            )
            if hub["direction"] == SENT and transfer is not None and transfer.status == InterbankStatus.PENDING:
                # 허브는 COMPLETED인데 우리가 결과를 아직 못 받았다
                if not settled:
                    checking.append(tid)
                    continue
                pending = _Line(SENT, transfer.to_bank, transfer.amount, transfer.created_at)
                if pending.view() != hub:
                    differs.append({"transfer_id": tid, "hub": hub, "ours": {**pending.view(), "status": "PENDING"}})
                    continue
                complete(db, transfer)  # 확정된 run이 근거: 중간 계정 → 정산 계정, 이 run에서 바로 맞춘다
                matched[tid] = pending
                resolved.append(tid)
            else:
                hub_only.append(await _hub_only(db, tid, hub))
        if resolved:
            await db.flush()  # 방금 남긴 COMPLETE 분개를 _settle의 UPDATE가 볼 수 있게

        listed = {str(t["transfer_id"]) for t in hub_transfers}
        ours_only = sorted(candidates.keys() - listed)
        stale_before = _as_utc(datetime.fromisoformat(detail["cutoff_at"])) - STALE_AFTER
        ours_only_stale = [tid for tid in ours_only if _as_utc(candidates[tid].created_at) < stale_before]

        hub_net = int(detail["position"]["net_amount"])
        our_net = sum(line.amount if line.direction == RECEIVED else -line.amount for line in matched.values())
        diff: dict = {"hub_only": hub_only, "differs": differs, "checking": checking,
                      "ours_only": ours_only, "ours_only_stale": ours_only_stale, "resolved_by_settlement": resolved}
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

    if result == ReconResult.MISMATCH:  # 자동 처리를 멈춘다. 허브에 dispute로 run_id와 차이 나는 transfer_id를 알린다
        logger.error("정산 run %d 대사 불일치: %s", run_id, row.diff_json)
    elif result == ReconResult.CHECKING:
        logger.info("정산 run %d 확인 중: 우리 쪽 PENDING %s", run_id, ", ".join(checking))
    if resolved:
        # 실시간 결과(SPEC 3.4)를 끝내 못 받은 거래다. 허브 응답 경로에 문제가 없는지 사람이 볼 만하다
        logger.warning("정산 run %d: 결과를 못 받은 PENDING %d건을 확정된 run을 근거로 완료 처리 (%s)",
                       run_id, len(resolved), ", ".join(resolved))
    if ours_only_stale:
        logger.warning("정산 run %d: cutoff보다 1시간 넘게 먼저 끝났는데 허브 run에 없는 거래 %s (허브 관리자 확인 필요)",
                       run_id, ", ".join(ours_only_stale))
    if settle_now:
        logger.info("정산 run %d 장부 정리: 허브 예치금 %+d원 (거래 %d건)", run_id, hub_net, len(matched))
    if status == "DRAFT" and await _report(db, row, hub_only, differs, diff.get("net")):
        # 허브가 방금 확정했다(전원 ack) 또는 그사이 확정·취소됐다: 상세를 다시 받아 이어서 한다
        again = await hub_client.settlement(run_id)
        if again.ok and str(again.body.get("status")) != "DRAFT":
            return await reconcile_run(db, again.body)
        if not again.ok:
            logger.warning("정산 run %d 확정 뒤 대사 파일을 받지 못함: %s %s (다음 주기에 다시)", run_id, again.status, again.error)
    return row


def _dispute_message(hub_only: list[dict], differs: list[dict], net: dict | None) -> str:
    parts = []
    if hub_only:
        parts.append(f"허브에만 있음 {len(hub_only)}건")
    if differs:
        parts.append(f"방향·금액·상대 은행 다름 {len(differs)}건")
    if net:
        parts.append(f"순액 다름 (허브 {net['hub']}원, AvengersBank {net['ours']}원)")
    return "AvengersBank 대사 불일치: " + ", ".join(parts)


async def _report(db: AsyncSession, row: SettlementReconciliation, hub_only: list[dict], differs: list[dict],
                  net: dict | None) -> bool:
    """DRAFT run의 대사 결과를 허브에 보낸다 (SPEC 10.8). 지금 걸려 있는 결과와 같으면 보내지 않는다.
    허브가 그 run을 이미 확정했다고 알려 오면(ack 응답 SETTLED, 또는 409 SETTLEMENT_NOT_DRAFT) True."""
    run_id = row.hub_run_id
    if row.result == ReconResult.MATCHED and row.acked_at is None:
        reply = await hub_client.ack_settlement(run_id)
        kind, values = "ack", {"acked_at": now_utc(), "disputed_at": None}
    elif row.result == ReconResult.MISMATCH and row.disputed_at is None:
        ids = [str(t["transfer_id"]) for t in hub_only + differs][:1000]
        reply = await hub_client.dispute_settlement(run_id, ids, _dispute_message(hub_only, differs, net))
        kind, values = "dispute", {"disputed_at": now_utc(), "acked_at": None}
    else:
        return False
    if reply.status == 409 and reply.error == "SETTLEMENT_NOT_DRAFT":
        logger.info("정산 run %d: %s를 보내려 했지만 허브에서 이미 DRAFT가 아님 (상세를 다시 본다)", run_id, kind)
        return True
    if not reply.ok:
        logger.warning("정산 run %d %s를 허브에 보내지 못함: %s %s (다음 주기에 다시)", run_id, kind, reply.status, reply.error)
        return False
    async with db.begin():  # 트랜잭션 밖에서 ORM 값을 바꾸면 새 트랜잭션이 저절로 열리므로 안에서 바꾼다 (row와 같은 객체)
        saved = await db.get(SettlementReconciliation, run_id, with_for_update=True)
        saved.acked_at, saved.disputed_at = values["acked_at"], values["disputed_at"]
    hub_status = str(reply.body.get("status"))
    logger.info("정산 run %d: 허브에 %s 보냄 (허브 상태 %s)", run_id, kind, hub_status)
    return kind == "ack" and hub_status == "SETTLED"


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
