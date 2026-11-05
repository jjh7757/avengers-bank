import pytest

from tests.conftest import DEPOSIT_PRODUCT, SAVINGS_PRODUCT, open_checking, terms_version

pytestmark = pytest.mark.anyio


async def balance_of(client, headers, account_id: int) -> int:
    response = await client.get(f"/accounts/checking/{account_id}", headers=headers)
    return response.json()["data"]["balance"]


async def test_transfer_success(client, user, other_user):
    source = await open_checking(client, user, balance=100_000)
    target = await open_checking(client, other_user)

    response = await client.post(
        "/transfers",
        headers=user,
        json={
            "from_checking_account_id": source["account_id"],
            "to_account_num": target["account_num"],
            "amount": 30_000,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["balance_after"] == 70_000
    assert data["to_holder_name"] == "브루스 배너"

    assert await balance_of(client, user, source["account_id"]) == 70_000
    assert await balance_of(client, other_user, target["account_id"]) == 30_000

    response = await client.get(f"/accounts/checking/{source['account_id']}/histories", headers=user)
    [history] = response.json()["data"]
    assert (history["type"], history["amount"]) == ("TRANSFER_OUT", -30_000)
    assert history["sending_account"] == target["account_num"]

    response = await client.get(
        f"/accounts/checking/{target['account_id']}/histories", headers=other_user
    )
    [history] = response.json()["data"]
    assert (history["type"], history["amount"]) == ("TRANSFER_IN", 30_000)


async def test_transfer_insufficient_balance(client, user, other_user):
    source = await open_checking(client, user, balance=10_000)
    target = await open_checking(client, other_user)

    response = await client.post(
        "/transfers",
        headers=user,
        json={"from_checking_account_id": source["account_id"], "to_account_num": target["account_num"], "amount": 10_001},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    # 실패한 이체는 잔액·내역에 흔적이 없어야 한다
    assert await balance_of(client, user, source["account_id"]) == 10_000
    response = await client.get(f"/accounts/checking/{source['account_id']}/histories", headers=user)
    assert response.json()["data"] == []


async def test_transfer_per_transfer_limit(client, user, other_user):
    source = await open_checking(
        client, user, balance=1_000_000, per_transfer_limit=100_000, daily_transfer_limit=1_000_000
    )
    target = await open_checking(client, other_user)

    response = await client.post(
        "/transfers",
        headers=user,
        json={"from_checking_account_id": source["account_id"], "to_account_num": target["account_num"], "amount": 100_001},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PER_TRANSFER_LIMIT_EXCEEDED"


async def test_transfer_daily_limit(client, user, other_user):
    source = await open_checking(
        client, user, balance=1_000_000, per_transfer_limit=100_000, daily_transfer_limit=150_000
    )
    target = await open_checking(client, other_user)
    body = {"from_checking_account_id": source["account_id"], "to_account_num": target["account_num"], "amount": 100_000}

    response = await client.post("/transfers", headers=user, json=body)
    assert response.status_code == 200

    response = await client.post("/transfers", headers=user, json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DAILY_LIMIT_EXCEEDED"

    # 남은 한도(5만원) 안에서는 된다
    response = await client.post("/transfers", headers=user, json={**body, "amount": 50_000})
    assert response.status_code == 200


async def test_transfer_from_others_account(client, user, other_user):
    victim = await open_checking(client, other_user, balance=100_000)
    mine = await open_checking(client, user)

    response = await client.post(
        "/transfers",
        headers=user,
        json={"from_checking_account_id": victim["account_id"], "to_account_num": mine["account_num"], "amount": 1_000},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_FORBIDDEN"


async def test_transfer_to_unknown_account(client, user):
    source = await open_checking(client, user, balance=100_000)
    response = await client.post(
        "/transfers",
        headers=user,
        json={"from_checking_account_id": source["account_id"], "to_account_num": "110-000-000000", "amount": 1_000},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


async def test_transfer_to_same_account(client, user):
    source = await open_checking(client, user, balance=100_000)
    response = await client.post(
        "/transfers",
        headers=user,
        json={"from_checking_account_id": source["account_id"], "to_account_num": source["account_num"], "amount": 1_000},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SAME_ACCOUNT"


async def test_pay_savings_default_monthly_payment(client, user):
    source = await open_checking(client, user, balance=500_000)
    response = await client.post(
        "/accounts/savings",
        headers=user,
        json={"product_id": SAVINGS_PRODUCT, "terms_version": terms_version("account", SAVINGS_PRODUCT), "term_months": 12, "monthly_payment": 200_000, "monthly_deposit_date": 10},
    )
    savings = response.json()["data"]

    response = await client.post(
        "/transfers/savings",
        headers=user,
        json={"from_checking_account_id": source["account_id"], "savings_account_id": savings["account_id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["amount"] == 200_000
    assert response.json()["data"]["balance_after"] == 300_000

    response = await client.get(f"/accounts/savings/{savings['account_id']}", headers=user)
    assert response.json()["data"]["balance"] == 200_000

    response = await client.get(f"/accounts/savings/{savings['account_id']}/histories", headers=user)
    [history] = response.json()["data"]
    assert (history["type"], history["amount"], history["from_account"]) == (
        "DEPOSIT", 200_000, source["account_num"]
    )

    response = await client.get(f"/accounts/checking/{source['account_id']}/histories", headers=user)
    assert response.json()["data"][0]["type"] == "SAVINGS_PAYMENT"


async def test_pay_deposit(client, user):
    source = await open_checking(client, user, balance=1_000_000)
    response = await client.post(
        "/accounts/deposit", headers=user, json={"product_id": DEPOSIT_PRODUCT, "terms_version": terms_version("account", DEPOSIT_PRODUCT), "term_months": 6}
    )
    deposit = response.json()["data"]

    response = await client.post(
        "/transfers/deposit",
        headers=user,
        json={"from_checking_account_id": source["account_id"], "deposit_account_id": deposit["account_id"], "amount": 1_000_000},
    )
    assert response.status_code == 200
    assert response.json()["data"]["balance_after"] == 0

    response = await client.post(
        "/transfers/deposit",
        headers=user,
        json={"from_checking_account_id": source["account_id"], "deposit_account_id": deposit["account_id"], "amount": 1},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INSUFFICIENT_BALANCE"


async def test_pay_into_others_savings_forbidden(client, user, other_user):
    source = await open_checking(client, user, balance=500_000)
    response = await client.post(
        "/accounts/savings",
        headers=other_user,
        json={"product_id": SAVINGS_PRODUCT, "terms_version": terms_version("account", SAVINGS_PRODUCT), "term_months": 12, "monthly_payment": 100_000, "monthly_deposit_date": 1},
    )
    others_savings = response.json()["data"]

    response = await client.post(
        "/transfers/savings",
        headers=user,
        json={"from_checking_account_id": source["account_id"], "savings_account_id": others_savings["account_id"]},
    )
    assert response.status_code == 403
