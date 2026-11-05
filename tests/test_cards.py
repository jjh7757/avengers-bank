import pytest

from tests.conftest import CREDIT_PRODUCT, DEBIT_PRODUCT, open_checking, terms_version

pytestmark = pytest.mark.anyio


async def issue_debit(client, headers, checking_account_id: int) -> dict:
    response = await client.post(
        "/cards/debit",
        headers=headers,
        json={"product_id": DEBIT_PRODUCT, "terms_version": terms_version("card", DEBIT_PRODUCT), "checking_account_id": checking_account_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_issue_and_list_cards(client, user):
    account = await open_checking(client, user)
    debit = await issue_debit(client, user, account["account_id"])
    assert debit["card_num"].startswith("9420-")
    assert len(debit["card_num"]) == 19

    response = await client.post(
        "/cards/credit",
        headers=user,
        json={"product_id": CREDIT_PRODUCT, "terms_version": terms_version("card", CREDIT_PRODUCT), "checking_account_id": account["account_id"], "payment_date": 14},
    )
    assert response.status_code == 201
    assert response.json()["data"]["payment_date"] == 14

    response = await client.get("/cards", headers=user)
    assert [c["card_type"] for c in response.json()["data"]] == ["credit", "debit"]


async def test_issue_with_wrong_product_type(client, user):
    account = await open_checking(client, user)
    response = await client.post(
        "/cards/debit",
        headers=user,
        json={"product_id": CREDIT_PRODUCT, "terms_version": terms_version("card", CREDIT_PRODUCT), "checking_account_id": account["account_id"]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PRODUCT_TYPE_MISMATCH"


async def test_issue_linked_to_others_account(client, user, other_user):
    others = await open_checking(client, other_user)
    response = await client.post(
        "/cards/debit",
        headers=user,
        json={"product_id": DEBIT_PRODUCT, "terms_version": terms_version("card", DEBIT_PRODUCT), "checking_account_id": others["account_id"]},
    )
    assert response.status_code == 403


async def test_debit_payment_withdraws_from_account(client, user):
    account = await open_checking(client, user, balance=50_000)
    card = await issue_debit(client, user, account["account_id"])
    path = f"/cards/debit/{card['card_id']}"

    response = await client.post(
        f"{path}/payments", headers=user, json={"place_of_use": "편의점", "used_amount": 12_000}
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["account_balance_after"] == 38_000
    assert data["accumulated_amount"] == 12_000

    response = await client.get(f"{path}/histories", headers=user)
    assert [(h["place_of_use"], h["used_amount"]) for h in response.json()["data"]] == [("편의점", 12_000)]

    response = await client.get(f"/accounts/checking/{account['account_id']}/histories", headers=user)
    [history] = response.json()["data"]
    assert (history["type"], history["amount"]) == ("CARD_PAYMENT", -12_000)


async def test_debit_payment_insufficient_balance(client, user):
    account = await open_checking(client, user, balance=1_000)
    card = await issue_debit(client, user, account["account_id"])

    response = await client.post(
        f"/cards/debit/{card['card_id']}/payments",
        headers=user,
        json={"place_of_use": "카페", "used_amount": 5_000},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INSUFFICIENT_BALANCE"

    response = await client.get(f"/cards/debit/{card['card_id']}", headers=user)
    assert response.json()["data"]["accumulated_amount"] == 0


async def test_credit_payment_accumulates_without_withdrawal(client, user):
    account = await open_checking(client, user, balance=0)
    response = await client.post(
        "/cards/credit",
        headers=user,
        json={"product_id": CREDIT_PRODUCT, "terms_version": terms_version("card", CREDIT_PRODUCT), "checking_account_id": account["account_id"], "payment_date": 25},
    )
    card = response.json()["data"]

    for amount in (30_000, 20_000):
        response = await client.post(
            f"/cards/credit/{card['card_id']}/payments",
            headers=user,
            json={"place_of_use": "마트", "used_amount": amount},
        )
        assert response.status_code == 200
    assert response.json()["data"]["accumulated_amount"] == 50_000
    assert response.json()["data"]["account_balance_after"] is None


async def test_others_card_forbidden(client, user, other_user):
    account = await open_checking(client, other_user, balance=10_000)
    card = await issue_debit(client, other_user, account["account_id"])

    response = await client.get(f"/cards/debit/{card['card_id']}", headers=user)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CARD_FORBIDDEN"

    response = await client.post(
        f"/cards/debit/{card['card_id']}/payments",
        headers=user,
        json={"place_of_use": "도둑질", "used_amount": 1_000},
    )
    assert response.status_code == 403


async def test_card_not_found(client, user):
    response = await client.get("/cards/credit/999", headers=user)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CARD_NOT_FOUND"
