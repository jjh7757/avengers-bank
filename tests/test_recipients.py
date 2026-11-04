import pytest

from tests.conftest import open_checking

pytestmark = pytest.mark.anyio


async def test_recipient_crud(client, user, other_user):
    mom = await open_checking(client, other_user)

    response = await client.post(
        "/recipients", headers=user, json={"account_num": mom["account_num"], "nickname": "엄마"}
    )
    assert response.status_code == 201, response.text
    recipient = response.json()["data"]
    assert recipient["holder_name"] == "브루스 배너"
    assert recipient["last_sent_at"] is None

    response = await client.get("/recipients", headers=user, params={"nickname": "엄마"})
    assert [r["account_num"] for r in response.json()["data"]] == [mom["account_num"]]

    response = await client.get("/recipients", headers=user, params={"nickname": "아빠"})
    assert response.json()["data"] == []

    response = await client.patch(
        f"/recipients/{recipient['recipient_id']}", headers=user, json={"nickname": "어머니"}
    )
    assert response.json()["data"]["nickname"] == "어머니"

    response = await client.delete(f"/recipients/{recipient['recipient_id']}", headers=user)
    assert response.status_code == 204
    response = await client.get("/recipients", headers=user)
    assert response.json()["data"] == []


async def test_recipient_unknown_account(client, user):
    response = await client.post(
        "/recipients", headers=user, json={"account_num": "110-000-000000", "nickname": "엄마"}
    )
    assert response.status_code == 404


async def test_recipient_duplicates(client, user, other_user):
    first = await open_checking(client, other_user)
    second = await open_checking(client, other_user)
    await client.post("/recipients", headers=user, json={"account_num": first["account_num"], "nickname": "엄마"})

    response = await client.post(
        "/recipients", headers=user, json={"account_num": first["account_num"], "nickname": "다른이름"}
    )
    assert response.json()["error"]["code"] == "RECIPIENT_ALREADY_EXISTS"

    response = await client.post(
        "/recipients", headers=user, json={"account_num": second["account_num"], "nickname": "엄마"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RECIPIENT_NICKNAME_EXISTS"


async def test_others_recipient_forbidden(client, user, other_user):
    account = await open_checking(client, user)
    response = await client.post(
        "/recipients", headers=other_user, json={"account_num": account["account_num"], "nickname": "토니"}
    )
    recipient_id = response.json()["data"]["recipient_id"]

    response = await client.delete(f"/recipients/{recipient_id}", headers=user)
    assert response.status_code == 403


async def test_transfer_updates_last_sent_at(client, user, other_user):
    source = await open_checking(client, user, balance=100_000)
    mom = await open_checking(client, other_user)
    await client.post("/recipients", headers=user, json={"account_num": mom["account_num"], "nickname": "엄마"})

    response = await client.post(
        "/transfers",
        headers=user,
        json={"from_checking_account_id": source["account_id"], "to_account_num": mom["account_num"], "amount": 50_000},
    )
    assert response.status_code == 200

    response = await client.get("/recipients", headers=user)
    assert response.json()["data"][0]["last_sent_at"] is not None


async def test_transfer_does_not_auto_register(client, user, other_user):
    source = await open_checking(client, user, balance=100_000)
    stranger = await open_checking(client, other_user)
    await client.post(
        "/transfers",
        headers=user,
        json={"from_checking_account_id": source["account_id"], "to_account_num": stranger["account_num"], "amount": 1_000},
    )
    response = await client.get("/recipients", headers=user)
    assert response.json()["data"] == []
