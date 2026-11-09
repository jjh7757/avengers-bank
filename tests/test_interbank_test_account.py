"""scripts/interbank_test_account.py: 다른 은행 연동 시험용 수취 계좌 (ClearingHub SPEC에 공개하는 값)."""

import importlib.util
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import select, update

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.interbank import service as interbank_service
from avengers_bank.domains.users.ci import virtual_ci
from avengers_bank.domains.users.models import User
from tests.conftest import open_checking

pytestmark = pytest.mark.anyio

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "interbank_test_account.py"
_spec = importlib.util.spec_from_file_location("interbank_test_account", _PATH)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

CI_KEY = "test-ci-key"


@pytest.fixture
def ci_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "ci_key", SecretStr(CI_KEY))


async def test_creates_account_and_keeps_it_on_rerun(client, ci_key):
    async with SessionLocal() as db:
        first = await script.ensure_test_account(db)
    assert (first.account_num, first.balance) == ("110-901-000001", 0)

    # 다른 은행이 보낸 돈이 쌓인 뒤 다시 실행해도 잔액·계좌는 그대로다
    async with SessionLocal() as db, db.begin():
        await db.execute(update(CheckingAccount).where(CheckingAccount.checking_account_id == first.checking_account_id)
                         .values(balance=5_000))
    async with SessionLocal() as db:
        again = await script.ensure_test_account(db)
    assert (again.checking_account_id, again.balance) == (first.checking_account_id, 5_000)
    async with SessionLocal() as db:
        assert len(list(await db.scalars(select(User).where(User.login_id == "interbank_test")))) == 1
        count = len(list(await db.scalars(select(CheckingAccount).where(CheckingAccount.account_num == "110-901-000001"))))
    assert count == 1


async def test_hub_sees_holder_and_own_account(client, ci_key):
    """수취 조회(4.1)에는 예금주 테스트수취, 본인 계좌 조회(9.4)에는 SPEC에 공개한 이름·생년월일·휴대폰의 CI로 나온다."""
    async with SessionLocal() as db:
        await script.ensure_test_account(db)
    async with SessionLocal() as db:
        assert await account_service.find_checking_holder(db, "110-901-000001") == "테스트수취"
    ci = virtual_ci(CI_KEY, "테스트수취", "20000101", "01011112222")
    async with SessionLocal() as db:
        accounts = await interbank_service.own_accounts_by_ci(db, ci)
    assert [a["account_num"] for a in accounts] == ["110-901-000001"]


async def test_cannot_log_in(client):
    async with SessionLocal() as db:
        await script.ensure_test_account(db)
    for password in ("demo1234!", "password1234", ""):
        response = await client.post("/users/login", json={"login_id": "interbank_test", "password": password})
        assert response.status_code != 200


async def test_refuses_when_number_belongs_to_someone_else(client, user):
    mine = await open_checking(client, user)
    async with SessionLocal() as db, db.begin():
        await db.execute(update(CheckingAccount).where(CheckingAccount.account_num == mine["account_num"])
                         .values(account_num="110-901-000001"))
    async with SessionLocal() as db:
        with pytest.raises(script.AccountNumTaken):
            await script.ensure_test_account(db)
