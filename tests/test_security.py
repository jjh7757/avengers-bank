"""2순위 보안: refresh 토큰(httpOnly 쿠키·회전·재사용 감지), 지난 로그인, 요청 제한, 이체 멱등성"""

import pytest

from avengers_bank.core.config import get_settings
from avengers_bank.core.rate_limit import transfer_requests
from avengers_bank.core.security import REFRESH_COOKIE
from tests.conftest import open_checking, set_balance, signup_and_login

pytestmark = pytest.mark.anyio

PASSWORD = "password1234"


async def signup(client, login_id="blackwidow"):
    await client.post(
        "/users/signup",
        json={"login_id": login_id, "password": PASSWORD, "name": "나타샤", "phone": "010-0000-0000"},
    )


def use_refresh_cookie(client, token: str) -> None:
    """다른 기기(또는 공격자)가 그 refresh 토큰을 들고 온 것처럼 쿠키를 바꿔 끼운다"""
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, token, domain="test.local", path="/")


async def login(client, login_id="blackwidow", password=PASSWORD):
    return await client.post("/users/login", json={"login_id": login_id, "password": password})


# ---- refresh 토큰 ----


async def test_login_sets_httponly_refresh_cookie(client):
    await signup(client)
    response = await login(client)
    assert response.status_code == 200
    assert response.json()["data"]["access_token"]
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{REFRESH_COOKIE}=")
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert response.headers["cache-control"] == "no-store"


async def test_refresh_rotates_token(client):
    await signup(client)
    await login(client)
    first = client.cookies[REFRESH_COOKIE]

    response = await client.post("/users/refresh")
    assert response.status_code == 200, response.text
    access = response.json()["data"]["access_token"]
    second = client.cookies[REFRESH_COOKIE]
    assert second != first

    me = await client.get("/users/me", headers={"Authorization": f"Bearer {access}"})
    assert me.json()["data"]["login_id"] == "blackwidow"


async def test_concurrent_refresh_within_grace(client):
    """탭 두 개가 같은 토큰으로 거의 동시에 갱신해도 로그아웃되지 않는다"""
    await signup(client)
    await login(client)
    shared = client.cookies[REFRESH_COOKIE]
    assert (await client.post("/users/refresh")).status_code == 200

    use_refresh_cookie(client, shared)
    response = await client.post("/users/refresh")
    assert response.status_code == 200, response.text
    assert client.cookies[REFRESH_COOKIE] != shared


async def test_reused_refresh_token_revokes_all(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "refresh_reuse_grace_seconds", 0)
    await signup(client)
    await login(client)
    stolen = client.cookies[REFRESH_COOKIE]
    assert (await client.post("/users/refresh")).status_code == 200
    current = client.cookies[REFRESH_COOKIE]

    # 이미 바꾼 토큰을 누가 다시 쓴다 → 탈취로 보고 모두 끊는다
    use_refresh_cookie(client, stolen)
    response = await client.post("/users/refresh")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    # 정상 사용자의 최신 토큰도 더는 쓸 수 없다
    use_refresh_cookie(client, current)
    response = await client.post("/users/refresh")
    assert response.status_code == 401


async def test_refresh_without_cookie(client):
    response = await client.post("/users/refresh")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REFRESH_TOKEN_REQUIRED"


async def test_logout_revokes_refresh_token(client):
    await signup(client)
    await login(client)
    token = client.cookies[REFRESH_COOKIE]

    response = await client.post("/users/logout")
    assert response.status_code == 200
    assert REFRESH_COOKIE not in client.cookies

    use_refresh_cookie(client, token)
    assert (await client.post("/users/refresh")).status_code == 401


async def test_previous_login_at(client):
    await signup(client)
    first = await login(client)
    headers = {"Authorization": f"Bearer {first.json()['data']['access_token']}"}
    me = (await client.get("/users/me", headers=headers)).json()["data"]
    assert me["last_login_at"] is not None
    assert me["previous_login_at"] is None  # 첫 로그인

    second = await login(client)
    headers = {"Authorization": f"Bearer {second.json()['data']['access_token']}"}
    again = (await client.get("/users/me", headers=headers)).json()["data"]
    assert again["previous_login_at"] == me["last_login_at"]


# ---- 요청 제한 ----


async def test_login_locked_after_five_failures(client):
    await signup(client)
    for _ in range(5):
        assert (await login(client, password="wrong-password")).status_code == 401

    # 맞는 비밀번호여도 잠시 막는다
    response = await login(client)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "TOO_MANY_LOGIN_ATTEMPTS"
    assert int(response.headers["retry-after"]) > 0


async def test_login_success_resets_failures(client):
    await signup(client)
    for _ in range(4):
        await login(client, password="wrong-password")
    assert (await login(client)).status_code == 200
    for _ in range(4):
        await login(client, password="wrong-password")
    assert (await login(client)).status_code == 200  # 성공하면 처음부터 다시 센다


async def setup_transfer(client, user, other_user, balance=1_000_000):
    source = await open_checking(client, user, balance=balance)
    target = await open_checking(client, other_user)
    return source, target, {"from_checking_account_id": source["account_id"], "to_account_num": target["account_num"]}


async def test_transfer_rate_limit(client, user, other_user, monkeypatch):
    monkeypatch.setattr(transfer_requests, "limit", 3)
    _, _, body = await setup_transfer(client, user, other_user)
    for _ in range(3):
        assert (await client.post("/transfers", headers=user, json={**body, "amount": 1_000})).status_code == 200
    response = await client.post("/transfers", headers=user, json={**body, "amount": 1_000})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "TOO_MANY_TRANSFER_REQUESTS"


async def test_pin_locked_after_five_wrong_pins(client, user, other_user):
    _, _, body = await setup_transfer(client, user, other_user, balance=2_000_000)
    body = {**body, "amount": 1_500_000}  # 처음 보내는 계좌로 큰 금액 → PIN 필요 (MEDIUM)
    await client.put("/users/me/pin", headers=user, json={"password": PASSWORD, "pin": "123456"})

    for _ in range(5):
        response = await client.post("/transfers", headers=user, json={**body, "pin": "000000"})
        assert response.json()["error"]["code"] == "INVALID_PIN"

    # 이제 맞는 PIN도 잠겨 있다
    response = await client.post("/transfers", headers=user, json={**body, "pin": "123456"})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "PIN_LOCKED"


# ---- 이체 멱등성 ----


async def test_same_idempotency_key_moves_money_once(client, user, other_user):
    source, target, body = await setup_transfer(client, user, other_user)
    headers = {**user, "Idempotency-Key": "transfer-key-0001"}
    request = {**body, "amount": 30_000}

    first = await client.post("/transfers", headers=headers, json=request)
    assert first.status_code == 200, first.text
    assert "idempotent-replayed" not in first.headers

    again = await client.post("/transfers", headers=headers, json=request)
    assert again.status_code == 200
    assert again.headers["idempotent-replayed"] == "true"
    assert again.json() == first.json()

    accounts = {a["account_id"]: a for a in (await client.get("/accounts", headers=user)).json()["data"]}
    assert accounts[source["account_id"]]["balance"] == 970_000  # 한 번만 빠졌다
    histories = (await client.get(f"/accounts/checking/{source['account_id']}/histories", headers=user)).json()["data"]
    assert len(histories) == 1


async def test_idempotency_key_with_different_body(client, user, other_user):
    _, _, body = await setup_transfer(client, user, other_user)
    headers = {**user, "Idempotency-Key": "transfer-key-0002"}
    assert (await client.post("/transfers", headers=headers, json={**body, "amount": 10_000})).status_code == 200

    response = await client.post("/transfers", headers=headers, json={**body, "amount": 20_000})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_failed_transfer_releases_key(client, user, other_user):
    source, _, body = await setup_transfer(client, user, other_user, balance=5_000)
    headers = {**user, "Idempotency-Key": "transfer-key-0003"}
    request = {**body, "amount": 10_000}

    response = await client.post("/transfers", headers=headers, json=request)
    assert response.json()["error"]["code"] == "INSUFFICIENT_BALANCE"

    # 실패한 요청은 키가 풀려서 같은 키로 다시 보낼 수 있다
    await set_balance(source["account_id"], 50_000)
    response = await client.post("/transfers", headers=headers, json=request)
    assert response.status_code == 200, response.text
    assert "idempotent-replayed" not in response.headers


async def test_idempotency_keys_are_per_user(client, user, other_user):
    _, _, body = await setup_transfer(client, user, other_user)
    other_source = await open_checking(client, other_user, balance=100_000)
    third = await signup_and_login(client, "thor", "토르")
    third_account = await open_checking(client, third)

    key = {"Idempotency-Key": "shared-key-0001"}
    assert (await client.post("/transfers", headers={**user, **key}, json={**body, "amount": 1_000})).status_code == 200
    response = await client.post(
        "/transfers", headers={**other_user, **key},
        json={"from_checking_account_id": other_source["account_id"], "to_account_num": third_account["account_num"], "amount": 2_000},
    )
    assert response.status_code == 200
    assert "idempotent-replayed" not in response.headers


async def test_invalid_idempotency_key(client, user, other_user):
    _, _, body = await setup_transfer(client, user, other_user)
    response = await client.post(
        "/transfers", headers={**user, "Idempotency-Key": "bad key!"}, json={**body, "amount": 1_000}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"
