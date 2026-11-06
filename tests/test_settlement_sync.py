"""허브 정산 대사와 장부 정리 (ClearingHub SPEC 10.6, SETTLEMENT_PLAN 8절 B1~B5).

허브는 test_interbank.py의 가짜 허브에 정산 목록(10.4)·대사 파일(10.5)을 더한 것으로 대신한다.
대사 파일은 테스트가 hub.runs에 직접 넣는다 (허브가 실제로 계산한 것처럼).
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank.hub_client import hub_client
from avengers_bank.domains.interbank.models import InterbankLedgerEntry, SettlementReconciliation
from avengers_bank.domains.interbank.service import ledger_balances, reconcile
from avengers_bank.domains.interbank.settlement_sync import STALE_AFTER, reconcile_run, sync_settlements
from avengers_bank.domains.interbank.signing import verify
from tests.conftest import open_checking
from tests.test_interbank import SECRET, FakeHub, hub_call, receive_payload, send

pytestmark = pytest.mark.anyio


class SettleHub(FakeHub):
    def __init__(self):
        self.runs: dict[int, dict] = {}  # run_id → 대사 파일 (10.5 응답)
        self.settle_down = False  # 정산 API가 응답하지 않음
        self.settle_unauthorized = False  # 정산 API가 401
        self.detail_calls: list[int] = []
        super().__init__()
        self._settlement_routes()

    def _settlement_routes(self):
        async def check(request: Request) -> JSONResponse | None:
            if self.settle_down:
                await asyncio.sleep(1)  # 우리 타임아웃(0.3초)보다 길게
            if self.settle_unauthorized:
                return JSONResponse(status_code=401, content={"error": "BANK_INACTIVE", "message": "비활성"})
            ok = verify(SECRET, request.headers.get("x-timestamp"), request.method, request.url.path,
                        await request.body(), request.headers.get("x-signature")) is None
            return None if ok else JSONResponse(status_code=401, content={"error": "SIGNATURE_INVALID", "message": "서명"})

        @self.app.get("/v1/settlements")
        async def settlements(request: Request):
            if (r := await check(request)) is not None:
                return r
            return {"settlements": [
                {k: d[k] for k in ("run_id", "settle_date", "cutoff_at", "status", "settled_at")}
                | {"net_amount": d["position"]["net_amount"], "result": d["position"]["result"]}
                for _, d in sorted(self.runs.items(), reverse=True) if d["status"] != "CANCELLED"
            ]}

        @self.app.get("/v1/settlements/{run_id}")
        async def settlement(run_id: int, request: Request):
            if (r := await check(request)) is not None:
                return r
            self.detail_calls.append(run_id)
            if run_id not in self.runs:
                return JSONResponse(status_code=404, content={"error": "SETTLEMENT_NOT_FOUND", "message": "없음"})
            return self.runs[run_id]

    def put_run(self, run_id: int, status: str, transfers: list[dict], *, net: int | None = None,
                cutoff_at: datetime | None = None) -> dict:
        """그 run의 대사 파일을 허브처럼 만든다. net을 주면 position.net_amount만 일부러 다르게 둔다.
        cutoff_at 기본값은 지금 + STALE_AFTER/2: 방금 만든 거래가 "오래된 ours_only"(cutoff − STALE_AFTER보다 먼저 끝남)로
        잡히지 않게 여유를 둔다. 예전 기본값(지금 + 1시간)은 여유가 0이라, cutoff를 초 단위로 자르는 사이 초가 바뀌면
        방금 받은 거래가 stale로 잡혀 test_ours_only_waits_for_next_run이 가끔 실패했다."""
        sent = [t for t in transfers if t["direction"] == "SENT"]
        recv = [t for t in transfers if t["direction"] == "RECEIVED"]
        cutoff = cutoff_at or datetime.now(timezone.utc) + STALE_AFTER / 2
        settled = status == "SETTLED"
        position = {
            "sent_count": len(sent), "sent_total": sum(t["amount"] for t in sent),
            "recv_count": len(recv), "recv_total": sum(t["amount"] for t in recv),
            "result": "OK" if settled else None, "balance_after": 1_000_000 if settled else None,
        }
        position["net_amount"] = position["recv_total"] - position["sent_total"] if net is None else net
        detail = {
            "run_id": run_id, "settle_date": "2026-11-06", "cutoff_at": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": status, "settled_at": "2026-11-07T00:40:00Z" if settled else None,
            "position": position,
            "transfers": [{**t, "finished_at": "2026-11-06T01:20:03Z"} for t in transfers],
        }
        self.runs[run_id] = detail
        return detail


@pytest.fixture
async def hub(client, monkeypatch):
    fake = SettleHub()
    http = AsyncClient(transport=ASGITransport(app=fake.app), base_url="http://hub")
    monkeypatch.setattr(hub_client, "_client", http)
    yield fake
    await http.aclose()


def sent(tid: str, amount: int = 50_000, bank: str = "902") -> dict:
    return {"transfer_id": tid, "direction": "SENT", "counterparty_bank": bank, "amount": amount}


def received(tid: str, amount: int = 30_000, bank: str = "902") -> dict:
    return {"transfer_id": tid, "direction": "RECEIVED", "counterparty_bank": bank, "amount": amount}


async def send_ok(client, user, source: dict, amount: int = 50_000, to_account: str = "110-123-0001") -> str:
    res = await send(client, user, source["account_id"], to_account, amount)
    assert res.status_code == 200, res.text
    return res.json()["data"]["transfer_id"]


async def receive_ok(client, source: dict, transfer_id: str, amount: int = 30_000) -> str:
    payload = {**receive_payload(source["account_num"], transfer_id), "amount": amount}
    assert (await hub_call(client, "POST", "/interbank/receive", payload)).status_code == 200
    return transfer_id


async def b1_books(client, user) -> tuple[list[str], str]:
    """B1의 거래: 우리 → 902 5만 원 2건(COMPLETED), 902 → 우리 3만 원 1건. (보낸 ID, 받은 ID)"""
    source = await open_checking(client, user, balance=200_000)
    out = [await send_ok(client, user, source), await send_ok(client, user, source)]
    return out, await receive_ok(client, source, "886313e1-3b8a-4372-9b90-0c9aee199e5d")


async def books() -> dict[str, int]:
    """내부 계정 잔액 (0 아닌 것). 대사(reconcile)도 함께 맞는지 확인한다."""
    async with SessionLocal() as db:
        assert await reconcile(db) == []
    async with SessionLocal() as db, db.begin():
        return {k: v for k, v in (await ledger_balances(db)).items() if v}


async def run_once(detail: dict) -> SettlementReconciliation | None:
    async with SessionLocal() as db:
        return await reconcile_run(db, detail)


async def sync() -> list[SettlementReconciliation]:
    async with SessionLocal() as db:
        return await sync_settlements(db)


async def stamped(run_id: int) -> list[str]:
    async with SessionLocal() as db, db.begin():
        rows = await db.scalars(select(InterbankLedgerEntry).where(InterbankLedgerEntry.hub_run_id == run_id))
        return sorted(f"{e.event}:{e.account}:{e.bank_code}:{e.amount}" for e in rows)


async def recon_rows() -> dict[int, SettlementReconciliation]:
    async with SessionLocal() as db, db.begin():
        return {r.hub_run_id: r for r in await db.scalars(select(SettlementReconciliation))}


def diff_of(row: SettlementReconciliation) -> dict:
    return json.loads(row.diff_json)


# ── B1·B2: 맞으면 장부 정리, 한 번만 ──────────────────────────────

async def test_b1_matched_run_settles_books(client, user, hub):
    out, inc = await b1_books(client, user)
    assert await books() == {"INTERBANK_SETTLEMENT:902": 70_000}  # 902에 줄 돈 10만 − 받을 돈 3만
    hub.put_run(12, "SETTLED", [sent(out[0]), sent(out[1]), received(inc)])

    [row] = await sync()
    assert (row.hub_run_id, row.result, row.hub_status) == (12, "MATCHED", "SETTLED")
    assert row.hub_net_amount == row.our_net_amount == -70_000
    assert row.settled_at is not None and diff_of(row) == {}
    # 정산 계정의 그 run 몫이 예치금으로 옮겨졌다: 우리가 7만을 냈으므로 허브 예치금이 7만 줄었다 (= position.net_amount)
    assert await books() == {"HUB_RESERVE": -70_000}
    assert await stamped(12) == [
        "COMPLETE:INTERBANK_SETTLEMENT:902:50000", "COMPLETE:INTERBANK_SETTLEMENT:902:50000",
        "RECEIVE:INTERBANK_SETTLEMENT:902:-30000",
        "SETTLE:HUB_RESERVE:000:-70000", "SETTLE:INTERBANK_SETTLEMENT:902:-70000",
    ]


async def test_b2_same_run_twice_settles_once(client, user, hub):
    out, inc = await b1_books(client, user)
    detail = hub.put_run(12, "SETTLED", [sent(out[0]), sent(out[1]), received(inc)])
    first = await run_once(detail)
    again = await run_once(detail)  # 직접 다시 (sync는 끝난 run을 고르지 않는다)
    assert first.result == again.result == "MATCHED"
    naive = lambda t: t.replace(tzinfo=None)  # noqa: E731  SQLite는 시간대 없이 돌려준다
    assert naive(again.settled_at) == naive(first.settled_at) and naive(again.checked_at) >= naive(first.checked_at)
    assert len(await recon_rows()) == 1
    assert await books() == {"HUB_RESERVE": -70_000}
    assert len(await stamped(12)) == 5  # SETTLE 2줄은 한 번만

    assert await sync() == []  # 이미 끝난 run은 다시 보지 않는다
    assert 12 not in hub.detail_calls


# ── B3: 허브에만 있음·내용이 다름 → 불일치, 장부 정리 안 함 ─────────

async def test_b3_hub_only_and_differs_are_mismatch(client, user, hub, caplog):
    out, inc = await b1_books(client, user)
    ghost = "00000000-0000-4000-8000-0000000000aa"  # 우리 장부에 없는 거래 (예: 입금 없이 COMPLETED라고 답함)
    hub.put_run(12, "SETTLED", [sent(out[0]), sent(out[1], 60_000), received(inc), received(ghost, 10_000)])

    with caplog.at_level(logging.ERROR):
        [row] = await sync()
    assert row.result == "MISMATCH" and row.settled_at is None
    diff = diff_of(row)
    assert diff["hub_only"] == [received(ghost, 10_000)]
    assert diff["differs"] == [{"transfer_id": out[1],
                                "hub": {"direction": "SENT", "counterparty_bank": "902", "amount": 60_000},
                                "ours": {"direction": "SENT", "counterparty_bank": "902", "amount": 50_000}}]
    assert any("정산 run 12 대사 불일치" in r.getMessage() and ghost in r.getMessage() for r in caplog.records)
    assert await books() == {"INTERBANK_SETTLEMENT:902": 70_000}  # 분개 없음
    assert await stamped(12) == []

    # 불일치는 끝나지 않은 run이라 다음 주기에 다시 본다
    await sync()
    assert hub.detail_calls == [12, 12]


async def test_b3_net_amount_differs_is_mismatch(client, user, hub):
    """거래는 모두 맞는데 허브 포지션 순액이 우리 계산과 다르면 불일치"""
    out, inc = await b1_books(client, user)
    hub.put_run(12, "SETTLED", [sent(out[0]), sent(out[1]), received(inc)], net=-60_000)
    [row] = await sync()
    assert row.result == "MISMATCH" and row.settled_at is None
    assert diff_of(row)["net"] == {"hub": -60_000, "ours": -70_000}
    assert await books() == {"INTERBANK_SETTLEMENT:902": 70_000}


# ── B4: DRAFT는 대사만, SETTLED가 되면 그때 정리 ─────────────────

async def test_b4_draft_then_settled(client, user, hub):
    out, inc = await b1_books(client, user)
    transfers = [sent(out[0]), sent(out[1]), received(inc)]
    hub.put_run(12, "DRAFT", transfers)
    [row] = await sync()
    assert (row.result, row.hub_status, row.settled_at) == ("MATCHED", "DRAFT", None)
    assert await books() == {"INTERBANK_SETTLEMENT:902": 70_000}
    assert await stamped(12) == []

    hub.put_run(12, "SETTLED", transfers)  # 허브 관리자가 확정
    [row] = await sync()
    assert (row.result, row.hub_status) == ("MATCHED", "SETTLED") and row.settled_at is not None
    assert await books() == {"HUB_RESERVE": -70_000}


# ── B5: 허브 응답 없음·거절 → 아무것도 안 하고 다음 주기 ─────────

async def test_b5_hub_unavailable(client, user, hub):
    out, inc = await b1_books(client, user)
    hub.put_run(12, "SETTLED", [sent(out[0]), sent(out[1]), received(inc)])

    hub.settle_down = True
    assert await sync() == []
    hub.settle_down, hub.settle_unauthorized = False, True
    assert await sync() == []
    assert await recon_rows() == {}
    assert await books() == {"INTERBANK_SETTLEMENT:902": 70_000}

    hub.settle_unauthorized = False  # 다음 주기
    [row] = await sync()
    assert row.result == "MATCHED" and row.settled_at is not None


# ── 확인 중: 허브는 COMPLETED, 우리는 아직 PENDING ───────────────

async def test_checking_until_pending_is_confirmed(client, user, hub):
    source = await open_checking(client, user, balance=100_000)
    tid = await send_ok(client, user, source, 30_000, to_account="110-123-0003")  # 허브 202 → 우리 PENDING
    detail = hub.put_run(12, "SETTLED", [sent(tid, 30_000)])

    row = await run_once(detail)
    assert row.result == "CHECKING" and row.settled_at is None
    assert diff_of(row) == {"checking": [tid]}
    assert await books() == {"INTERBANK_SUSPENSE": 30_000}

    # 허브에서는 이미 COMPLETED. 대사가 결과를 물어(SPEC 3.4) 마무리한 뒤 다시 맞춰 본다
    hub.transfers[tid]["status"] = "COMPLETED"
    [row] = await sync()
    assert row.result == "MATCHED" and row.settled_at is not None
    assert await books() == {"HUB_RESERVE": -30_000}


# ── 우리에게만 있는 거래: 다음 run으로, 오래되면 경고 ────────────

async def test_ours_only_waits_for_next_run(client, user, hub, caplog):
    source = await open_checking(client, user, balance=100_000)
    out = await send_ok(client, user, source, 40_000)
    inc = await receive_ok(client, source, "16fd2706-8baf-433b-82eb-8c7fada847da", 25_000)
    assert await books() == {"INTERBANK_SETTLEMENT:902": 15_000}

    # run 1에는 보낸 것만 (받은 것은 허브 기록 시각이 cutoff 뒤였다)
    hub.put_run(1, "SETTLED", [sent(out, 40_000)])
    [row] = await sync()
    assert row.result == "MATCHED" and diff_of(row) == {"ours_only": [inc]}
    assert await books() == {"INTERBANK_SETTLEMENT:902": -25_000, "HUB_RESERVE": -40_000}

    # run 2에 받은 것이 들어온다
    hub.put_run(2, "SETTLED", [received(inc, 25_000)])
    [row] = await sync()
    assert row.hub_run_id == 2 and row.result == "MATCHED" and diff_of(row) == {}
    assert await books() == {"HUB_RESERVE": -15_000}
    assert len(await stamped(1)) == 3 and len(await stamped(2)) == 3

    # cutoff보다 1시간 넘게 먼저 끝났는데도 run에 없으면: MATCHED는 막지 않고 경고만
    late = await send_ok(client, user, source, 10_000)
    hub.put_run(3, "SETTLED", [], cutoff_at=datetime.now(timezone.utc) + STALE_AFTER * 2)
    with caplog.at_level(logging.WARNING):
        [row] = await sync()
    assert row.result == "MATCHED" and row.settled_at is not None
    assert diff_of(row) == {"ours_only": [late], "ours_only_stale": [late]}
    assert any("허브 run에 없는 거래" in r.getMessage() and late in r.getMessage() for r in caplog.records)
    assert await books() == {"HUB_RESERVE": -15_000, "INTERBANK_SETTLEMENT:902": 10_000}


# ── 어떤 run을 어떤 순서로 보는가 ───────────────────────────────

async def test_sync_picks_unfinished_runs_in_order(client, user, hub):
    hub.put_run(3, "SETTLED", [])
    assert [r.hub_run_id for r in await sync()] == [3]  # 0건 run도 MATCHED로 끝낸다

    hub.put_run(5, "DRAFT", [])
    hub.put_run(4, "SETTLED", [])
    hub.detail_calls.clear()
    rows = await sync()
    assert [r.hub_run_id for r in rows] == [4, 5]  # run_id 오름차순, 끝난 3은 안 본다
    assert hub.detail_calls == [4, 5]
    assert (await recon_rows())[5].settled_at is None

    # 허브 관리자가 DRAFT를 취소: 목록에서 사라지지만 끝나지 않은 run이라 상세로 보고, CANCELLED면 기록을 지운다
    hub.runs[5]["status"] = "CANCELLED"
    hub.detail_calls.clear()
    assert await sync() == []
    assert hub.detail_calls == [5]
    assert sorted(await recon_rows()) == [3, 4]
    assert await books() == {}


async def test_cancelled_detail_is_ignored(client, user, hub):
    out, inc = await b1_books(client, user)
    detail = hub.put_run(7, "CANCELLED", [])
    detail["transfers"] = [sent(out[0])]  # 내용이 있어도 보지 않는다
    assert await run_once(detail) is None
    assert await recon_rows() == {}
    assert await books() == {"INTERBANK_SETTLEMENT:902": 70_000}
