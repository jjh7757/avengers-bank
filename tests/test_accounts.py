from datetime import date

import pytest

from avengers_bank.domains.accounts.service import add_months
from tests.conftest import DEPOSIT_PRODUCT, SAVINGS_PRODUCT, open_checking

pytestmark = pytest.mark.anyio


async def test_open_checking_and_list(client, user):
    account = await open_checking(client, user, nickname="생활비")
    assert account["account_num"].startswith("110-")
    assert len(account["account_num"]) == 14
    assert account["per_transfer_limit"] == 5_000_000
    assert account["daily_transfer_limit"] == 10_000_000

    response = await client.get("/accounts", headers=user)
    data = response.json()["data"]
    assert [(a["account_type"], a["nickname"]) for a in data] == [("checking", "생활비")]


async def test_open_deposit_and_savings(client, user):
    response = await client.post(
        "/accounts/deposit", headers=user, json={"product_id": DEPOSIT_PRODUCT, "term_months": 12}
    )
    assert response.status_code == 201
    deposit = response.json()["data"]
    assert deposit["account_num"].startswith("220-")
    assert deposit["maturity_date"] is not None
    assert deposit["per_transfer_limit"] is None

    response = await client.post(
        "/accounts/savings",
        headers=user,
        json={
            "product_id": SAVINGS_PRODUCT,
            "term_months": 12,
            "monthly_payment": 300_000,
            "monthly_deposit_date": 25,
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["account_num"].startswith("330-")

    response = await client.get("/accounts", headers=user)
    assert {a["account_type"] for a in response.json()["data"]} == {"deposit", "savings"}


async def test_open_with_wrong_product_type(client, user):
    response = await client.post(
        "/accounts/checking", headers=user, json={"product_id": DEPOSIT_PRODUCT}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PRODUCT_TYPE_MISMATCH"


async def test_open_with_unknown_product(client, user):
    response = await client.post("/accounts/checking", headers=user, json={"product_id": 999})
    assert response.status_code == 404


async def test_open_with_invalid_limits(client, user):
    response = await client.post(
        "/accounts/checking",
        headers=user,
        json={"product_id": 1, "per_transfer_limit": 2_000_000, "daily_transfer_limit": 1_000_000},
    )
    assert response.status_code == 422


async def test_requires_login(client):
    response = await client.get("/accounts")
    assert response.status_code == 401


async def test_get_account_detail_and_forbidden(client, user, other_user):
    account = await open_checking(client, user)
    path = f"/accounts/checking/{account['account_id']}"

    response = await client.get(path, headers=user)
    assert response.status_code == 200
    assert response.json()["data"]["account_num"] == account["account_num"]

    response = await client.get(path, headers=other_user)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_FORBIDDEN"

    response = await client.get(f"{path}/histories", headers=other_user)
    assert response.status_code == 403


async def test_get_account_not_found(client, user):
    response = await client.get("/accounts/savings/999", headers=user)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


async def test_invalid_account_type(client, user):
    response = await client.get("/accounts/loan/1", headers=user)
    assert response.status_code == 422


async def test_update_nickname_and_limits(client, user):
    account = await open_checking(client, user)
    path = f"/accounts/checking/{account['account_id']}"

    response = await client.patch(
        path, headers=user, json={"nickname": "월급통장", "per_transfer_limit": 1_000_000}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["nickname"] == "월급통장"
    assert data["per_transfer_limit"] == 1_000_000
    assert data["daily_transfer_limit"] == 10_000_000

    # 기존 1일 한도(1,000만)보다 큰 1회 한도
    response = await client.patch(path, headers=user, json={"per_transfer_limit": 20_000_000})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_TRANSFER_LIMIT"


async def test_update_limit_on_savings_rejected(client, user):
    response = await client.post(
        "/accounts/savings",
        headers=user,
        json={"product_id": SAVINGS_PRODUCT, "term_months": 6, "monthly_payment": 100_000, "monthly_deposit_date": 1},
    )
    account_id = response.json()["data"]["account_id"]
    response = await client.patch(
        f"/accounts/savings/{account_id}", headers=user, json={"daily_transfer_limit": 1_000}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TRANSFER_LIMIT_NOT_SUPPORTED"


def test_add_months_clamps_end_of_month():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 4), 12) == date(2027, 11, 4)
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
