import pytest

pytestmark = pytest.mark.anyio

SIGNUP = {
    "login_id": "ironman",
    "password": "password1234",
    "name": "토니 스타크",
    "phone": "010-1234-5678",
}


async def test_root(client):
    response = await client.get("/")
    assert response.status_code == 200


async def test_signup_login_me(client):
    response = await client.post("/users/signup", json=SIGNUP)
    assert response.status_code == 201

    response = await client.post(
        "/users/login", json={"login_id": SIGNUP["login_id"], "password": SIGNUP["password"]}
    )
    assert response.status_code == 200
    token = response.json()["data"]["access_token"]

    response = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["data"]["login_id"] == SIGNUP["login_id"]


async def test_update_me(client, user):
    response = await client.patch(
        "/users/me", headers=user, json={"nick_name": "아이언맨", "phone": "010-9999-8888"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["name"], data["nick_name"], data["phone"]) == ("토니 스타크", "아이언맨", "010-9999-8888")

    response = await client.get("/users/me", headers=user)
    assert response.json()["data"]["nick_name"] == "아이언맨"

    response = await client.patch("/users/me", headers=user, json={"nick_name": None})
    assert response.json()["data"]["nick_name"] is None


async def test_update_me_cannot_clear_required_field(client, user):
    response = await client.patch("/users/me", headers=user, json={"name": None})
    assert response.status_code == 400


async def test_update_me_requires_login(client):
    response = await client.patch("/users/me", json={"name": "누구"})
    assert response.status_code == 401


async def test_signup_duplicate_login_id(client):
    await client.post("/users/signup", json=SIGNUP)
    response = await client.post("/users/signup", json=SIGNUP)
    assert response.status_code == 409
