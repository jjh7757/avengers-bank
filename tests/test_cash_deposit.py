"""시연용 가상 입금 POST /accounts/checking/{id}/cash-deposit"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.interbank.models import InterbankLedgerEntry
from avengers_bank.domains.interbank.service import ledger_balances, reconcile
from tests.conftest import open_checking

pytestmark = pytest.mark.anyio


def path(account: dict) -> str:
    return f"/accounts/checking/{account['account_id']}/cash-deposit"


async def test_cash_deposit_adds_balance_and_history(client, user):
    account = await open_checking(client, user, balance=1_000)

    response = await client.post(path(account), headers=user, json={"amount": 50_000})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["account_num"] == account["account_num"]
    assert data["amount"] == 50_000
    assert data["balance_after"] == 51_000

    detail = (await client.get(f"/accounts/checking/{account['account_id']}", headers=user)).json()["data"]
    assert detail["balance"] == 51_000

    histories = (await client.get(f"/accounts/checking/{account['account_id']}/histories", headers=user)).json()["data"]
    assert [(h["type"], h["amount"], h["from_account"], h["sending_account"]) for h in histories] == [
        ("CASH_DEPOSIT", 50_000, None, account["account_num"])
    ]


async def test_cash_deposit_per_request_limit(client, user):
    account = await open_checking(client, user)

    response = await client.post(path(account), headers=user, json={"amount": 1_000_001})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CASH_DEPOSIT_LIMIT_EXCEEDED"

    response = await client.post(path(account), headers=user, json={"amount": 1_000_000})
    assert response.status_code == 200


async def test_cash_deposit_daily_limit_is_per_user(client, user, other_user):
    first = await open_checking(client, user)
    second = await open_checking(client, user)
    for account in (first, second, first):
        response = await client.post(path(account), headers=user, json={"amount": 1_000_000})
        assert response.status_code == 200, response.text

    # 다른 계좌로 넣어도 같은 사용자면 하루 300만원에서 막힌다
    response = await client.post(path(second), headers=user, json={"amount": 1})
    assert response.status_code == 400
    body = response.json()["error"]
    assert body["code"] == "CASH_DEPOSIT_DAILY_LIMIT_EXCEEDED"
    assert "0원" in body["message"]
    detail = (await client.get(f"/accounts/checking/{second['account_id']}", headers=user)).json()["data"]
    assert detail["balance"] == 1_000_000

    # 다른 사용자는 따로 센다
    others = await open_checking(client, other_user)
    response = await client.post(path(others), headers=other_user, json={"amount": 1_000_000})
    assert response.status_code == 200


async def test_cash_deposit_partial_remaining_message(client, user):
    account = await open_checking(client, user)
    for amount in (1_000_000, 1_000_000, 700_000):
        assert (await client.post(path(account), headers=user, json={"amount": amount})).status_code == 200

    response = await client.post(path(account), headers=user, json={"amount": 500_000})
    assert response.status_code == 400
    assert "300,000원" in response.json()["error"]["message"]


async def test_cash_deposit_only_own_account(client, user, other_user):
    account = await open_checking(client, user)

    response = await client.post(path(account), headers=other_user, json={"amount": 10_000})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_FORBIDDEN"

    response = await client.post("/accounts/checking/999/cash-deposit", headers=user, json={"amount": 10_000})
    assert response.status_code == 404

    response = await client.post(path(account), json={"amount": 10_000})
    assert response.status_code == 401


@pytest.mark.parametrize("amount", [0, -1, "abc"])
async def test_cash_deposit_invalid_amount(client, user, amount):
    account = await open_checking(client, user)
    response = await client.post(path(account), headers=user, json={"amount": amount})
    assert response.status_code == 422


async def test_cash_deposit_does_not_use_transfer_limit(client, user):
    """가상 입금은 이체 1일 한도 계산(TRANSFER_OUT - TRANSFER_REFUND)에 끼지 않는다."""
    account = await open_checking(client, user)
    assert (await client.post(path(account), headers=user, json={"amount": 1_000_000})).status_code == 200
    async with SessionLocal() as db, db.begin():
        used = await account_repository.sum_transfer_out_since(
            db, account["account_id"], datetime.now(timezone.utc) - timedelta(days=1)
        )
    assert used == 0


async def vault_state() -> tuple[int, list[str], list[tuple]]:
    """금고 현금 잔액, 대사 불일치 목록, 금고 분개 줄"""
    async with SessionLocal() as db:
        problems = await reconcile(db)
    async with SessionLocal() as db, db.begin():
        balance = (await ledger_balances(db)).get("CASH_VAULT", 0)
        rows = (await db.execute(
            select(InterbankLedgerEntry.transfer_id, InterbankLedgerEntry.event, InterbankLedgerEntry.amount)
            .where(InterbankLedgerEntry.account == "CASH_VAULT").order_by(InterbankLedgerEntry.entry_id)
        )).all()
    return balance, problems, [tuple(r) for r in rows]


async def test_cash_deposit_posts_to_cash_vault(client, user, other_user):
    """고객 잔액이 늘어난 만큼 내부 계정 금고 현금(CASH_VAULT)도 늘고, 대사가 맞는다."""
    assert await vault_state() == (0, [], [])

    mine = await open_checking(client, user)
    others = await open_checking(client, other_user)
    assert (await client.post(path(mine), headers=user, json={"amount": 50_000})).status_code == 200
    assert (await client.post(path(others), headers=other_user, json={"amount": 30_000})).status_code == 200
    # 한도에 걸린 입금은 분개도 남지 않는다
    assert (await client.post(path(mine), headers=user, json={"amount": 2_000_000})).status_code == 400

    balance, problems, rows = await vault_state()
    assert balance == 80_000
    assert problems == []
    histories = (await client.get(f"/accounts/checking/{mine['account_id']}/histories", headers=user)).json()["data"]
    assert rows[0] == (f"cash:{histories[0]['history_id']}", "CASH_DEPOSIT", 50_000)
    assert [r[2] for r in rows] == [50_000, 30_000]


async def test_reconcile_catches_deposit_without_vault_entry(client, user):
    """금고 분개 없이 고객 잔액만 늘어난 가상 입금이 있으면 대사가 잡는다."""
    account = await open_checking(client, user)
    assert (await client.post(path(account), headers=user, json={"amount": 10_000})).status_code == 200
    async with SessionLocal() as db, db.begin():
        await db.execute(delete(InterbankLedgerEntry).where(InterbankLedgerEntry.account == "CASH_VAULT"))

    _, problems, _ = await vault_state()
    assert problems == ["CASH_VAULT: 분개 잔액 0 ≠ 거래 기록 10,000"]
