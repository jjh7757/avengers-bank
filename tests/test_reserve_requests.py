"""허브 예치금 입금·인출 신청 (ClearingHub SPEC 10.9). 허브는 test_interbank.py의 가짜 허브에 신청 API를 더한 것으로 대신한다.

가짜 허브는 실제 허브처럼 request_ref로 멱등이고, 결정(승인·거절)은 테스트가 hub.decide로 내린다 (허브 관리자 역할).
"""

import asyncio

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.interbank import reserve_requests as rr
from avengers_bank.domains.interbank.hub_client import hub_client
from avengers_bank.domains.interbank.models import HubReserveRequest, InterbankLedgerEntry
from avengers_bank.domains.interbank.service import ledger_balances, reconcile
from avengers_bank.domains.interbank.signing import verify_ed25519
from tests.conftest import open_checking
from tests.test_interbank import FakeHub

pytestmark = pytest.mark.anyio


class ReserveHub(FakeHub):
    def __init__(self):
        self.requests: dict[int, dict] = {}
        self.by_ref: dict[str, int] = {}
        self.balance = 0
        self.down = False  # 응답 안 함 (타임아웃)
        self.lose_reply = False  # 접수는 하고 응답만 잃어버림 (한 번)
        self.reject_next: tuple[str, str] | None = None  # 다음 신청을 4xx로 거절
        self.create_calls = 0
        super().__init__()
        self._reserve_routes()

    def decide(self, hub_id: int, status: str, reason: str | None = None) -> None:
        req = self.requests[hub_id]
        req["status"] = status
        if status == "APPROVED":
            self.balance += req["amount"] if req["kind"] == "DEPOSIT" else -req["amount"]
            req["entry_id"], req["balance_after"] = hub_id * 10, self.balance
        if status == "REJECTED":
            req["reject_reason"] = reason

    def _reserve_routes(self):
        app = self.app

        async def check(request: Request) -> JSONResponse | None:
            if self.down:
                await asyncio.sleep(1)  # 우리 타임아웃(0.3초)보다 길게
            ok = verify_ed25519(self.bank_public_key, request.headers.get("x-timestamp"), request.method,
                                request.url.path, await request.body(), request.headers.get("x-signature")) is None
            return None if ok else JSONResponse(status_code=401, content={"error": "SIGNATURE_INVALID", "message": "서명"})

        @app.post("/v1/reserve/requests")
        async def create(request: Request):
            if (r := await check(request)) is not None:
                return r
            self.create_calls += 1
            body = await request.json()
            if self.reject_next:
                code, message = self.reject_next
                self.reject_next = None
                return JSONResponse(status_code=400, content={"error": code, "message": message})
            if body["request_ref"] in self.by_ref:
                return JSONResponse(status_code=200, content=self.requests[self.by_ref[body["request_ref"]]])
            hub_id = len(self.requests) + 1
            self.requests[hub_id] = {"request_id": hub_id, "request_ref": body["request_ref"], "kind": body["kind"],
                                     "amount": body["amount"], "memo": body["memo"], "status": "PENDING",
                                     "reject_reason": None, "entry_id": None, "balance_after": None}
            self.by_ref[body["request_ref"]] = hub_id
            if self.lose_reply:
                self.lose_reply = False
                await asyncio.sleep(1)
            return JSONResponse(status_code=201, content=self.requests[hub_id])

        @app.get("/v1/reserve/requests/{hub_id}")
        async def get_one(hub_id: int, request: Request):
            if (r := await check(request)) is not None:
                return r
            return self.requests[hub_id]

        @app.post("/v1/reserve/requests/{hub_id}/cancel")
        async def cancel(hub_id: int, request: Request):
            if (r := await check(request)) is not None:
                return r
            req = self.requests[hub_id]
            if req["status"] != "PENDING":
                return JSONResponse(status_code=409, content={"error": "RESERVE_REQUEST_NOT_PENDING", "message": "결정됨"})
            req["status"] = "CANCELLED"
            return req


@pytest.fixture
async def hub(client, monkeypatch):
    fake = ReserveHub()
    http = AsyncClient(transport=ASGITransport(app=fake.asgi), base_url="http://hub")
    monkeypatch.setattr(hub_client, "_client", http)
    yield fake
    await http.aclose()


async def _fund_vault(client, user, amount: int = 1_000_000) -> None:
    """가상 입금으로 금고 현금을 만든다 (회당 100만 원까지)."""
    account = await open_checking(client, user)
    res = await client.post(f"/accounts/checking/{account['account_id']}/cash-deposit", headers=user, json={"amount": amount})
    assert res.status_code == 200, res.text


async def _reconcile() -> list[str]:
    async with SessionLocal() as db:
        return await reconcile(db)


async def _balances() -> dict[str, int]:
    async with SessionLocal() as db:
        return await ledger_balances(db)


async def _moves() -> list[tuple[str, str, int]]:
    async with SessionLocal() as db:
        rows = await db.scalars(select(InterbankLedgerEntry).where(InterbankLedgerEntry.event == "RESERVE_MOVE")
                                .order_by(InterbankLedgerEntry.entry_id))
        return [(e.transfer_id, e.account, e.amount) for e in rows]


async def test_deposit_request_approved_moves_vault_to_reserve(client, user, hub):
    await _fund_vault(client, user, 1_000_000)
    async with SessionLocal() as db:
        req = await rr.request(db, "DEPOSIT", 600_000, "11월 예치")
    assert req.status == "PENDING" and req.hub_request_id == 1 and req.request_ref.startswith("avb-")
    assert hub.requests[1]["memo"] == "11월 예치"
    assert await _moves() == []  # 신청만으로는 장부가 바뀌지 않는다

    async with SessionLocal() as db:
        assert await rr.sync(db) == []  # 아직 결정 전
    hub.decide(1, "APPROVED")
    async with SessionLocal() as db:
        changed = await rr.sync(db)
    assert [(r.request_id, r.status, r.hub_balance_after) for r in changed] == [(req.request_id, "APPROVED", 600_000)]
    assert await _moves() == [(f"reserve:{req.request_id}", "HUB_RESERVE", 600_000),
                              (f"reserve:{req.request_id}", "CASH_VAULT", -600_000)]
    balances = await _balances()
    assert balances["HUB_RESERVE"] == 600_000 and balances["CASH_VAULT"] == 400_000
    assert await _reconcile() == []
    async with SessionLocal() as db:
        assert await rr.sync(db) == []  # 열린 신청이 없다
        assert not await rr.has_open(db)
    assert len(await _moves()) == 2  # 한 번만


async def test_withdraw_approved_moves_back(client, user, hub):
    await _fund_vault(client, user, 500_000)
    async with SessionLocal() as db:
        dep = await rr.request(db, "DEPOSIT", 500_000)
    hub.decide(dep.hub_request_id, "APPROVED")
    async with SessionLocal() as db:
        await rr.sync(db)
        wd = await rr.request(db, "WITHDRAW", 200_000)
    hub.decide(wd.hub_request_id, "APPROVED")
    async with SessionLocal() as db:
        await rr.sync(db)
    balances = await _balances()
    assert balances["HUB_RESERVE"] == 300_000 and balances["CASH_VAULT"] == 200_000
    assert await _reconcile() == []


async def test_deposit_limited_by_vault_cash(client, user, hub):
    await _fund_vault(client, user, 300_000)
    async with SessionLocal() as db:
        with pytest.raises(ApiException) as exc:
            await rr.request(db, "DEPOSIT", 300_001)
        assert exc.value.code == "INSUFFICIENT_VAULT_CASH" and "300,000원" in exc.value.message
        await rr.request(db, "DEPOSIT", 200_000)
        with pytest.raises(ApiException) as exc:  # 결정을 기다리는 입금 신청도 뺀다
            await rr.request(db, "DEPOSIT", 100_001)
        assert "100,000원" in exc.value.message
        await rr.request(db, "WITHDRAW", 9_999_999)  # 인출 한도는 허브가 본다
    assert hub.create_calls == 2


async def test_rejected(client, user, hub):
    await _fund_vault(client, user)
    async with SessionLocal() as db:
        req = await rr.request(db, "DEPOSIT", 100_000)
    hub.decide(req.hub_request_id, "REJECTED", "입금 내역 없음")
    async with SessionLocal() as db:
        (row,) = await rr.sync(db)
    assert row.status == "REJECTED" and row.reject_reason == "입금 내역 없음" and row.booked_at is None
    assert await _moves() == []


async def test_hub_refuses_on_create(client, user, hub):
    hub.reject_next = ("INSUFFICIENT_RESERVE", "인출할 수 있는 금액(0원)보다 많이 신청했습니다 (5000원)")
    async with SessionLocal() as db:
        req = await rr.request(db, "WITHDRAW", 5_000)
    assert req.status == "FAILED" and req.reject_reason.startswith("INSUFFICIENT_RESERVE: 인출할 수 있는")
    async with SessionLocal() as db:
        assert not await rr.has_open(db)


async def test_lost_reply_is_resent_with_same_ref(client, user, hub):
    """허브가 접수했는데 응답을 못 받았다 → SENDING으로 남고, sync가 같은 request_ref로 다시 보내 한 건으로 맞춘다."""
    await _fund_vault(client, user)
    hub.lose_reply = True
    async with SessionLocal() as db:
        req = await rr.request(db, "DEPOSIT", 100_000)
    assert req.status == "SENDING" and req.hub_request_id is None
    hub.decide(1, "APPROVED")  # 그사이 허브 관리자가 승인했다
    async with SessionLocal() as db:
        (row,) = await rr.sync(db)
    assert row.status == "APPROVED" and row.hub_request_id == 1 and row.booked_at is not None
    assert len(hub.requests) == 1 and hub.create_calls == 2
    assert (await _balances())["HUB_RESERVE"] == 100_000 and await _reconcile() == []


async def test_hub_down_keeps_sending(client, user, hub):
    await _fund_vault(client, user)
    hub.down = True
    async with SessionLocal() as db:
        req = await rr.request(db, "DEPOSIT", 100_000)
        assert req.status == "SENDING"
        assert await rr.sync(db) == []  # 여전히 응답 없음
    hub.down = False
    async with SessionLocal() as db:
        (row,) = await rr.sync(db)
    assert row.status == "PENDING" and len(hub.requests) == 1


async def test_cancel(client, user, hub):
    await _fund_vault(client, user)
    async with SessionLocal() as db:
        a = await rr.request(db, "DEPOSIT", 100_000)
        b = await rr.request(db, "DEPOSIT", 100_000)
        assert (await rr.cancel(db, a.request_id)).status == "CANCELLED"
        assert hub.requests[a.hub_request_id]["status"] == "CANCELLED"
        with pytest.raises(ApiException) as exc:
            await rr.cancel(db, a.request_id)
        assert exc.value.code == "RESERVE_REQUEST_NOT_PENDING"
    # 취소를 보내기 직전에 허브가 승인했다 → 허브 409, 우리는 승인으로 맞추고 분개한다
    hub.decide(b.hub_request_id, "APPROVED")
    async with SessionLocal() as db:
        row = await rr.cancel(db, b.request_id)
    assert row.status == "APPROVED" and row.booked_at is not None
    assert [m[2] for m in await _moves()] == [100_000, -100_000]


async def test_validation(client, hub):
    async with SessionLocal() as db:
        for kind, amount, memo in (("ADJUST", 1, ""), ("DEPOSIT", 0, ""), ("WITHDRAW", 10**12 + 1, ""),
                                   ("WITHDRAW", 1, "m" * 201)):
            with pytest.raises(ApiException) as exc:
                await rr.request(db, kind, amount, memo)
            assert exc.value.code == "VALIDATION_ERROR"
        assert (await db.scalars(select(HubReserveRequest))).all() == []
