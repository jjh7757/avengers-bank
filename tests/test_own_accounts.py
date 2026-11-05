"""다른 은행 내 계좌 (ClearingHub SPEC 9절): 가상 CI, 불러오기(동의 기록), 참조값 이체, 허브 → 우리 /interbank/accounts."""

import json
from datetime import timedelta

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr
from sqlalchemy import select, update

from avengers_bank.core.clock import real_now_utc
from avengers_bank.core.config import get_settings
from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank.models import HubAccountQuery, OwnAccountLookup, OwnAccountRef
from avengers_bank.domains.users.ci import virtual_ci
from avengers_bank.domains.users.models import User
from tests.conftest import new_chat_session, open_checking
from tests.test_interbank import FakeHub, hub_call, interbank_list
from tests.test_interbank import hub as _hub  # noqa: F401  (fixture 등록용)

pytestmark = pytest.mark.anyio
CI_KEY = "test-ci-key"
BIRTH = "19700529"


@pytest.fixture(autouse=True)
def ci_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "ci_key", SecretStr(CI_KEY))


class LookupHub(FakeHub):
    """가짜 허브에 SPEC 9.2를 붙인다. 같은 사람(CI)이면 SimBank 계좌 하나를 준다."""

    def __init__(self):
        self.lookups: list[dict] = []
        self.lookup_status = 200
        super().__init__()

        @self.app.post("/v1/accounts/lookup")
        async def lookup(request: Request):
            data = json.loads(await request.body())
            self.lookups.append(data)
            if self.lookup_status != 200:
                return JSONResponse(status_code=self.lookup_status, content={"error": "TOO_MANY_LOOKUPS", "message": "횟수"})
            accounts = [{"bank_code": "902", "bank_name": "SimBank", "account_masked": "110-***-0001",
                         "product_name": "자유입출금", "account_ref": "acr_" + data["consent_id"][-12:]}]
            return {"lookup_id": "lk-1", "accounts": accounts,
                    "banks": [{"bank_code": "902", "result": "OK", "count": 1}, {"bank_code": "903", "result": "UNSUPPORTED"}]}


@pytest.fixture
async def hub(client, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from avengers_bank.domains.interbank.hub_client import hub_client

    fake = LookupHub()
    http = AsyncClient(transport=ASGITransport(app=fake.app), base_url="http://hub")
    monkeypatch.setattr(hub_client, "_client", http)
    yield fake
    await http.aclose()


async def set_birth(client, headers, birth: str = BIRTH):
    res = await client.patch("/users/me", headers=headers, json={"birth_date": birth})
    assert res.status_code == 200, res.text


async def load_own(client, headers):
    return await client.post("/transfers/own-accounts", headers=headers, json={"consent": True})


async def send_ref(client, headers, account_id: int, ref: str, to_bank: str = "902", **extra):
    return await client.post("/transfers", headers=headers, json={
        "from_checking_account_id": account_id, "to_bank": to_bank, "to_account_num": "110-***-0001",
        "to_account_ref": ref, "amount": 40_000, **extra,
    })


async def test_birth_date_required(client, user, hub):
    res = await load_own(client, user)
    assert res.status_code == 400 and res.json()["error"]["code"] == "BIRTH_DATE_REQUIRED"
    assert hub.lookups == []
    res = await client.patch("/users/me", headers=user, json={"birth_date": "19701332"})
    assert res.status_code == 422  # 날짜 형식


async def test_consent_required(client, user, hub):
    await set_birth(client, user)
    res = await client.post("/transfers/own-accounts", headers=user, json={"consent": False})
    assert res.status_code == 422


async def test_load_then_send_to_own_account(client, user, hub):
    await set_birth(client, user)
    res = await load_own(client, user)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    [account] = data["accounts"]
    assert (account["bank_name"], account["account_masked"], account["product_name"]) == ("SimBank", "110-***-0001", "자유입출금")
    assert {b["bank_code"]: b["result"] for b in data["banks"]} == {"902": "OK", "903": "UNSUPPORTED"}

    # 허브에는 원본이 아니라 가상 CI와 동의 ID만 간다
    [sent] = hub.lookups
    assert sent["ci"] == virtual_ci(CI_KEY, "토니 스타크", BIRTH, "010-0000-0000")
    assert sent["consent_id"].startswith("avb-") and set(sent) == {"ci", "consent_id"}
    async with SessionLocal() as db:
        lookup = await db.get(OwnAccountLookup, sent["consent_id"])
        assert (lookup.hub_lookup_id, lookup.account_count) == ("lk-1", 1)

    source = await open_checking(client, user, balance=100_000)
    res = await send_ref(client, user, source["account_id"], account["account_ref"])
    assert res.status_code == 200, res.text
    result = res.json()["data"]
    # 예금주는 허브(받는 은행)가 알려 준 이름. 가짜 허브는 늘 김철수라고 답한다 (응답 전에는 내 이름으로 저장)
    assert (result["status"], result["to_holder_name"], result["to_account_num"]) == ("COMPLETED", "김철수", "110-***-0001")
    assert result["risk_level"] == "LOW"  # 내 계좌라 '처음 보내는 계좌'로 보지 않는다
    [call] = hub.transfer_calls
    assert call["to_account_ref"] == account["account_ref"] and "to_account" not in call
    assert (await interbank_list(client, user))[0]["to_account"] == "110-***-0001"


async def test_ref_rules(client, user, other_user, hub):
    await set_birth(client, user)
    ref = (await load_own(client, user)).json()["data"]["accounts"][0]["account_ref"]
    source = await open_checking(client, user, balance=100_000)
    other_source = await open_checking(client, other_user, balance=100_000)

    res = await send_ref(client, other_user, other_source["account_id"], ref)  # 남의 참조값
    assert res.json()["error"]["code"] == "ACCOUNT_REF_INVALID"
    res = await send_ref(client, user, source["account_id"], ref, to_bank="903")  # 은행이 다름
    assert res.json()["error"]["code"] == "ACCOUNT_REF_INVALID"
    res = await send_ref(client, user, source["account_id"], ref, to_bank="901")  # 우리 은행
    assert res.json()["error"]["code"] == "ACCOUNT_REF_NOT_ALLOWED"
    session_id = await new_chat_session(client, user)
    res = await send_ref(client, user, source["account_id"], ref, session_id=session_id)  # 채팅에서는 못 씀
    assert res.json()["error"]["code"] == "ACCOUNT_REF_NOT_ALLOWED"

    async with SessionLocal() as db, db.begin():
        await db.execute(update(OwnAccountRef).values(expires_at=real_now_utc() - timedelta(seconds=1)))
    res = await send_ref(client, user, source["account_id"], ref)  # 만료
    assert res.json()["error"]["code"] == "ACCOUNT_REF_INVALID"
    assert hub.transfer_calls == []
    assert (await client.get(f"/accounts/checking/{source['account_id']}", headers=user)).json()["data"]["balance"] == 100_000


async def test_hub_limit_and_unavailable(client, user, hub, monkeypatch):
    await set_birth(client, user)
    hub.lookup_status = 429
    res = await load_own(client, user)
    assert res.status_code == 429 and res.json()["error"]["code"] == "TOO_MANY_LOOKUPS"
    hub.lookup_status = 500
    assert (await load_own(client, user)).status_code == 503
    monkeypatch.setattr(get_settings(), "ci_key", None)
    res = await load_own(client, user)
    assert res.status_code == 503 and len(hub.lookups) == 2


async def test_ci_follows_profile(client, user):
    async def stored_ci():
        async with SessionLocal() as db:
            return await db.scalar(select(User.ci).where(User.login_id == "ironman"))

    assert await stored_ci() is None  # 생년월일이 없으면 CI도 없다
    await set_birth(client, user)
    assert await stored_ci() == virtual_ci(CI_KEY, "토니 스타크", BIRTH, "01000000000")
    await client.patch("/users/me", headers=user, json={"phone": "010-1111-2222"})
    assert await stored_ci() == virtual_ci(CI_KEY, "토니 스타크", BIRTH, "010-1111-2222")
    assert (await client.get("/users/me", headers=user)).json()["data"]["birth_date"] == BIRTH


async def test_signup_with_birth_date(client):
    res = await client.post("/users/signup", json={"login_id": "thor", "password": "password1234", "name": "토르",
                                                   "phone": "010-3333-4444", "birth_date": "19650101"})
    assert res.status_code == 201, res.text
    async with SessionLocal() as db:
        assert await db.scalar(select(User.ci).where(User.login_id == "thor")) == virtual_ci(CI_KEY, "토르", "19650101", "01033334444")


async def test_interbank_accounts_for_hub(client, user):
    await set_birth(client, user)
    first = await open_checking(client, user)
    second = await open_checking(client, user)
    ci = virtual_ci(CI_KEY, "토니 스타크", BIRTH, "01000000000")

    res = await hub_call(client, "POST", "/interbank/accounts", {"ci": ci})
    assert res.status_code == 200, res.text
    accounts = res.json()["accounts"]
    assert [a["account_num"] for a in accounts] == [first["account_num"], second["account_num"]]
    assert all(a["product_name"] for a in accounts) and set(accounts[0]) == {"account_num", "product_name"}

    res = await hub_call(client, "POST", "/interbank/accounts", {"ci": "0" * 64})
    assert res.status_code == 200 and res.json() == {"accounts": []}  # 고객이 없어도 빈 목록
    res = await hub_call(client, "POST", "/interbank/accounts", {"ci": "XYZ"})
    assert res.status_code == 422 and res.json()["error"] == "VALIDATION_ERROR"
    res = await hub_call(client, "POST", "/interbank/accounts", {"ci": ci}, secret="wrong")
    assert res.status_code == 401

    # 조회 기록 (SPEC 9.4 규칙 5): 응답한 조회만, 고객이 없던 조회도 계좌 0개로 남는다
    async with SessionLocal() as db:
        queries = (await db.scalars(select(HubAccountQuery).order_by(HubAccountQuery.query_id))).all()
    assert [(q.ci, q.account_count) for q in queries] == [(ci, 2), ("0" * 64, 0)]
    assert all(q.queried_at is not None for q in queries)
