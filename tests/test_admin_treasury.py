"""관리자 계정·권한과 자금 관리 API (/admin/treasury, /admin/audit-logs).

허브는 test_reserve_requests.py의 가짜 허브(예치금 신청 API)에 GET /v1/reserve를 더한 것으로 대신한다.
"""

import asyncio
import io

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.admin import cli
from avengers_bank.domains.admin.models import AdminAuditLog
from avengers_bank.domains.interbank import reserve_requests as rr
from avengers_bank.domains.interbank.models import HubReserveRequest
from avengers_bank.domains.interbank.service import reconcile
from avengers_bank.domains.users.models import User
from tests.test_reserve_requests import ReserveHub, _fund_vault

pytestmark = pytest.mark.anyio

ADMIN_PASSWORD = "admin-pass-1234"


class TreasuryHub(ReserveHub):
    def __init__(self):
        super().__init__()
        self.net_debit_cap = 1_000_000_000
        self.exposure = 0

        @self.app.get("/v1/reserve")
        async def reserve():
            if self.down:
                await asyncio.sleep(1)  # 우리 타임아웃(0.3초)보다 길게
                return JSONResponse(status_code=200, content={})
            return {"bank_code": "901", "balance": self.balance, "net_debit_cap": self.net_debit_cap,
                    "exposure": self.exposure, "available": self.balance + self.net_debit_cap - self.exposure}


@pytest.fixture
async def hub(client, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from avengers_bank.domains.interbank.hub_client import hub_client

    fake = TreasuryHub()
    http = AsyncClient(transport=ASGITransport(app=fake.asgi), base_url="http://hub")
    monkeypatch.setattr(hub_client, "_client", http)
    yield fake
    await http.aclose()


async def _login(client, login_id: str, password: str) -> dict:
    res = await client.post("/users/login", json={"login_id": login_id, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['data']['access_token']}"}


@pytest.fixture
async def admin(client):
    async with SessionLocal() as db:
        await cli.create_admin(db, "treasurer", "자금 관리자", "010-9999-0000", ADMIN_PASSWORD)
    return await _login(client, "treasurer", ADMIN_PASSWORD)


async def _audit_logs() -> list[AdminAuditLog]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.log_id))).all())


async def _customer_balances() -> list[int]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(CheckingAccount.balance).order_by(CheckingAccount.checking_account_id))).all())


async def _reconcile() -> list[str]:
    async with SessionLocal() as db:
        return await reconcile(db)


# ---- 권한 ----

async def test_admin_api_requires_login_and_admin_role(client, user):
    res = await client.get("/admin/treasury")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    for method, path in (("GET", "/admin/treasury"), ("GET", "/admin/treasury/reserve-requests"),
                         ("POST", "/admin/treasury/reserve-requests/sync"), ("GET", "/admin/audit-logs")):
        res = await client.request(method, path, headers=user)
        assert res.status_code == 403, path
        assert res.json()["error"]["code"] == "ADMIN_REQUIRED"
    res = await client.post("/admin/treasury/reserve-requests", headers=user,
                            json={"kind": "DEPOSIT", "amount": 1000, "memo": ""})
    assert res.status_code == 403
    assert await _audit_logs() == []  # 권한이 없는 시도는 관리자 행동이 아니다 (로그인 기록·접근 로그로 본다)


async def test_signup_cannot_become_admin(client):
    res = await client.post("/users/signup", json={"login_id": "villain", "password": "password1234", "name": "로키",
                                                   "phone": "010-1111-2222", "role": "ADMIN"})
    assert res.status_code == 201, res.text
    assert res.json()["data"]["role"] == "CUSTOMER"
    headers = await _login(client, "villain", "password1234")
    res = await client.patch("/users/me", headers=headers, json={"role": "ADMIN"})
    assert res.status_code == 200 and res.json()["data"]["role"] == "CUSTOMER"
    assert (await client.get("/admin/treasury", headers=headers)).status_code == 403


async def test_me_shows_role(client, admin, user):
    assert (await client.get("/users/me", headers=admin)).json()["data"]["role"] == "ADMIN"
    assert (await client.get("/users/me", headers=user)).json()["data"]["role"] == "CUSTOMER"


async def test_revoked_admin_is_blocked_with_same_token(client, admin, hub):
    assert (await client.get("/admin/treasury", headers=admin)).status_code == 200
    async with SessionLocal() as db:
        await cli.revoke_admin(db, "treasurer")
    res = await client.get("/admin/treasury", headers=admin)  # 토큰은 그대로인데 역할은 DB에서 다시 읽는다
    assert res.status_code == 403 and res.json()["error"]["code"] == "ADMIN_REQUIRED"


# ---- CLI ----

async def test_cli_create_revoke_list(client, user):
    async with SessionLocal() as db:
        created = await cli.create_admin(db, "ops-admin", "운영", "010-2222-3333", ADMIN_PASSWORD)
    assert created.role == "ADMIN"
    async with SessionLocal() as db:
        assert [u.login_id for u in await cli.list_admins(db)] == ["ops-admin"]
    for args, message in ((("ops-admin", "운영", "010-2222-3333", ADMIN_PASSWORD), "이미 있는"),
                          (("ironman", "고객", "010-2222-3333", ADMIN_PASSWORD), "이미 있는"),  # 고객 계정을 올리지 않는다
                          (("short-pw", "운영", "010-2222-3333", "1234567"), "8자")):
        async with SessionLocal() as db:
            with pytest.raises(cli.AdminCliError, match=message):
                await cli.create_admin(db, *args)
    async with SessionLocal() as db:
        await cli.revoke_admin(db, "ops-admin")
    async with SessionLocal() as db:
        assert await cli.list_admins(db) == []
        with pytest.raises(cli.AdminCliError, match="관리자가 아닙니다"):
            await cli.revoke_admin(db, "ironman")
    async with SessionLocal() as db:
        with pytest.raises(cli.AdminCliError, match="없는 아이디"):
            await cli.revoke_admin(db, "nobody")
    # 비밀번호가 해시로 저장되어 로그인할 수 있다
    async with SessionLocal() as db:
        await cli.create_admin(db, "ops-admin2", "운영2", "010-2222-4444", ADMIN_PASSWORD)
    await _login(client, "ops-admin2", ADMIN_PASSWORD)


async def test_cli_main_reads_admin_password_env(client, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO())  # 터미널이 아님
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    assert await cli.main(["create-admin", "env-admin", "--name", "환경", "--phone", "010-5555-6666"]) == 0
    assert await cli.main(["list-admins"]) == 0
    assert "env-admin" in capsys.readouterr().out
    monkeypatch.delenv("ADMIN_PASSWORD")
    assert await cli.main(["create-admin", "env-admin2", "--name", "환경", "--phone", "010-5555-6666"]) == 1
    assert "ADMIN_PASSWORD" in capsys.readouterr().err


def test_cli_password_env_wins_over_tty(monkeypatch):
    """Windows에서는 입력을 NUL로 돌려도 isatty()가 True다: ADMIN_PASSWORD가 있으면 getpass를 부르지 않는다."""

    class FakeTty(io.StringIO):
        def isatty(self):
            return True

    def no_prompt(*_):
        raise AssertionError("getpass를 부르면 안 된다")

    monkeypatch.setattr(cli.sys, "stdin", FakeTty())
    monkeypatch.setattr(cli.getpass, "getpass", no_prompt)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    assert cli.read_password() == ADMIN_PASSWORD


# ---- 현황 ----

async def test_treasury_values(client, user, admin, hub):
    await _fund_vault(client, user, 1_000_000)
    res = await client.get("/admin/treasury", headers=admin)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["vault_cash"] == 1_000_000
    assert data["ledger_hub_reserve"] == 0
    assert data["hub_reserve"] == {"bank_code": "901", "balance": 0, "net_debit_cap": 1_000_000_000, "exposure": 0,
                                   "available": 1_000_000_000}
    assert data["hub_reserve_error"] is None
    assert data["deposit_available"] == 1_000_000 and data["open_deposit_amount"] == 0
    assert data["open_request_count"] == 0 and data["suspense_balance"] == 0
    assert data["reconcile_problems"] == [] and data["interbank_enabled"] is True

    # 결정 대기 입금이 있으면 신청 가능 금액이 줄어든다
    res = await client.post("/admin/treasury/reserve-requests", headers=admin,
                            json={"kind": "DEPOSIT", "amount": 300_000, "memo": "예치"})
    assert res.status_code == 201, res.text
    data = (await client.get("/admin/treasury", headers=admin)).json()["data"]
    assert data["deposit_available"] == 700_000 and data["open_deposit_amount"] == 300_000
    assert data["open_request_count"] == 1 and data["open_deposit_count"] == 1 and data["open_withdraw_count"] == 0


async def test_treasury_when_hub_down(client, admin, hub):
    hub.down = True
    data = (await client.get("/admin/treasury", headers=admin)).json()["data"]
    assert data["hub_reserve"] is None and data["hub_reserve_error"] == "HUB_TIMEOUT"
    assert data["vault_cash"] == 0  # 우리 장부 값은 그대로 보인다


async def test_interbank_disabled(client, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "hub_url", None)
    data = (await client.get("/admin/treasury", headers=admin)).json()["data"]
    assert data["interbank_enabled"] is False
    assert data["hub_reserve"] is None and data["hub_reserve_error"] == "INTERBANK_DISABLED"
    res = await client.post("/admin/treasury/reserve-requests", headers=admin,
                            json={"kind": "WITHDRAW", "amount": 1000, "memo": ""})
    assert res.status_code == 503 and res.json()["error"]["code"] == "INTERBANK_DISABLED"
    res = await client.post("/admin/treasury/reserve-requests/sync", headers=admin)
    assert res.status_code == 503
    logs = await _audit_logs()
    assert [(log.action, log.result, log.error_code) for log in logs] == [
        ("RESERVE_REQUEST_CREATE", "FAILED", "INTERBANK_DISABLED"), ("RESERVE_SYNC", "FAILED", "INTERBANK_DISABLED")]


# ---- 신청 ----

async def test_deposit_over_vault_is_refused_and_audited(client, user, admin, hub):
    await _fund_vault(client, user, 500_000)
    res = await client.post("/admin/treasury/reserve-requests", headers=admin,
                            json={"kind": "DEPOSIT", "amount": 500_001, "memo": "너무 많이"})
    assert res.status_code == 400 and res.json()["error"]["code"] == "INSUFFICIENT_VAULT_CASH"
    assert hub.create_calls == 0
    logs = await _audit_logs()
    assert len(logs) == 1
    log = logs[0]
    assert (log.action, log.result, log.error_code, log.target) == ("RESERVE_REQUEST_CREATE", "FAILED",
                                                                    "INSUFFICIENT_VAULT_CASH", None)
    assert log.detail == {"kind": "DEPOSIT", "amount": 500_001, "memo": "너무 많이"}
    assert log.client_ip == "127.0.0.1" and log.admin_user_id == 2  # 고객(ironman)이 1번
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(HubReserveRequest)) == 0


async def test_deposit_approved_sync_books_ledger(client, user, admin, hub):
    await _fund_vault(client, user, 1_000_000)
    before = await _customer_balances()
    res = await client.post("/admin/treasury/reserve-requests", headers=admin,
                            json={"kind": "DEPOSIT", "amount": 600_000, "memo": "11월 예치"})
    assert res.status_code == 201, res.text
    req = res.json()["data"]
    assert req["status"] == "PENDING" and req["hub_request_id"] == 1 and req["booked_at"] is None
    assert len(hub.requests) == 1 and hub.requests[1]["amount"] == 600_000 and hub.requests[1]["memo"] == "11월 예치"
    log = (await _audit_logs())[-1]
    assert (log.action, log.result, log.target) == ("RESERVE_REQUEST_CREATE", "OK", str(req["request_id"]))
    assert log.detail == {"kind": "DEPOSIT", "amount": 600_000, "memo": "11월 예치", "status": "PENDING",
                          "hub_request_id": 1}

    hub.decide(1, "APPROVED")
    res = await client.post("/admin/treasury/reserve-requests/sync", headers=admin)
    assert res.status_code == 200, res.text
    changed = res.json()["data"]
    assert [(r["request_id"], r["status"]) for r in changed] == [(req["request_id"], "APPROVED")]
    assert changed[0]["booked_at"] is not None and changed[0]["hub_balance_after"] == 600_000
    log = (await _audit_logs())[-1]
    assert (log.action, log.result) == ("RESERVE_SYNC", "OK")
    assert log.detail == {"changed": [{"request_id": req["request_id"], "status": "APPROVED"}]}

    data = (await client.get("/admin/treasury", headers=admin)).json()["data"]
    assert data["vault_cash"] == 400_000 and data["ledger_hub_reserve"] == 600_000
    assert data["hub_reserve"]["balance"] == 600_000
    assert data["reconcile_problems"] == [] and await _reconcile() == []
    assert data["open_request_count"] == 0
    assert await _customer_balances() == before  # 고객 계좌 잔액은 그대로

    # 인출도 같은 길: 승인되면 예치금 → 금고
    res = await client.post("/admin/treasury/reserve-requests", headers=admin,
                            json={"kind": "WITHDRAW", "amount": 100_000})
    assert res.status_code == 201 and res.json()["data"]["memo"] == ""
    hub.decide(2, "APPROVED")
    await client.post("/admin/treasury/reserve-requests/sync", headers=admin)
    data = (await client.get("/admin/treasury", headers=admin)).json()["data"]
    assert data["vault_cash"] == 500_000 and data["ledger_hub_reserve"] == 500_000 and data["reconcile_problems"] == []
    assert await _customer_balances() == before


async def test_hub_refusal_is_audited_as_failed(client, admin, hub):
    hub.reject_next = ("INSUFFICIENT_RESERVE", "예치금이 모자랍니다")
    res = await client.post("/admin/treasury/reserve-requests", headers=admin,
                            json={"kind": "WITHDRAW", "amount": 5000, "memo": ""})
    assert res.status_code == 201  # 신청 기록은 남는다 (허브가 거절한 FAILED)
    data = res.json()["data"]
    assert data["status"] == "FAILED" and data["reject_reason"].startswith("INSUFFICIENT_RESERVE")
    log = (await _audit_logs())[-1]
    assert (log.result, log.error_code, log.target) == ("FAILED", "INSUFFICIENT_RESERVE", str(data["request_id"]))


async def test_validation_errors(client, admin, hub):
    for body in ({"kind": "TRANSFER", "amount": 1000}, {"kind": "DEPOSIT", "amount": 0},
                 {"kind": "DEPOSIT", "amount": 1000, "memo": "x" * 201}):
        res = await client.post("/admin/treasury/reserve-requests", headers=admin, json=body)
        assert res.status_code == 422, body


async def test_cancel_list_and_audit_logs(client, user, admin, hub):
    await _fund_vault(client, user, 1_000_000)
    first = (await client.post("/admin/treasury/reserve-requests", headers=admin,
                               json={"kind": "DEPOSIT", "amount": 200_000, "memo": "취소할 것"})).json()["data"]
    second = (await client.post("/admin/treasury/reserve-requests", headers=admin,
                                json={"kind": "WITHDRAW", "amount": 50_000})).json()["data"]

    res = await client.post(f"/admin/treasury/reserve-requests/{first['request_id']}/cancel", headers=admin)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["status"] == "CANCELLED" and hub.requests[1]["status"] == "CANCELLED"
    res = await client.post(f"/admin/treasury/reserve-requests/{first['request_id']}/cancel", headers=admin)
    assert res.status_code == 409 and res.json()["error"]["code"] == "RESERVE_REQUEST_NOT_PENDING"
    res = await client.post("/admin/treasury/reserve-requests/999/cancel", headers=admin)
    assert res.status_code == 404 and res.json()["error"]["code"] == "RESERVE_REQUEST_NOT_FOUND"

    rows = (await client.get("/admin/treasury/reserve-requests", headers=admin)).json()["data"]
    assert [(r["request_id"], r["kind"], r["status"]) for r in rows] == [
        (second["request_id"], "WITHDRAW", "PENDING"), (first["request_id"], "DEPOSIT", "CANCELLED")]
    # 취소한 입금은 신청 가능 금액에서 빠진다
    assert (await client.get("/admin/treasury", headers=admin)).json()["data"]["deposit_available"] == 1_000_000

    res = await client.get("/admin/audit-logs", headers=admin)
    assert res.status_code == 200
    logs = res.json()["data"]
    assert [(log["action"], log["result"], log["error_code"], log["target"]) for log in logs] == [
        ("RESERVE_REQUEST_CANCEL", "FAILED", "RESERVE_REQUEST_NOT_FOUND", "999"),
        ("RESERVE_REQUEST_CANCEL", "FAILED", "RESERVE_REQUEST_NOT_PENDING", str(first["request_id"])),
        ("RESERVE_REQUEST_CANCEL", "OK", None, str(first["request_id"])),
        ("RESERVE_REQUEST_CREATE", "OK", None, str(second["request_id"])),
        ("RESERVE_REQUEST_CREATE", "OK", None, str(first["request_id"])),
    ]
    assert logs[2]["detail"] == {"kind": "DEPOSIT", "amount": 200_000, "status": "CANCELLED"}
    assert all(log["admin_login_id"] == "treasurer" for log in logs)
    assert len((await client.get("/admin/audit-logs?limit=2", headers=admin)).json()["data"]) == 2
    assert (await client.get("/admin/audit-logs?limit=201", headers=admin)).status_code == 422


async def test_concurrent_deposits_cannot_exceed_vault(client, user, admin, hub, monkeypatch):
    """동시에 온 입금 신청 둘이 같은 금고 잔액을 보고 둘 다 통과하지 않는다 (reserve_requests._deposit_guard)."""
    await _fund_vault(client, user, 1_000_000)
    real_open_deposits = rr._open_deposits

    async def slow_open_deposits(db):  # 검사와 행 저장 사이를 벌려 다른 요청이 끼어들 틈을 만든다
        value = await real_open_deposits(db)
        await asyncio.sleep(0.05)
        return value

    monkeypatch.setattr(rr, "_open_deposits", slow_open_deposits)
    results = await asyncio.gather(*(
        client.post("/admin/treasury/reserve-requests", headers=admin, json={"kind": "DEPOSIT", "amount": 700_000})
        for _ in range(3)
    ))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 400, 400], [r.text for r in results]
    assert {r.json()["error"]["code"] for r in results if r.status_code == 400} == {"INSUFFICIENT_VAULT_CASH"}
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(HubReserveRequest)) == 1
    assert sorted(log.result for log in await _audit_logs()) == ["FAILED", "FAILED", "OK"]


async def test_admin_role_column_defaults_to_customer(client, user):
    async with SessionLocal() as db:
        assert (await db.scalars(select(User.role))).all() == ["CUSTOMER"]
