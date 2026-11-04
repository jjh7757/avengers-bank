import pytest

from avengers_bank.agents import llm
from avengers_bank.agents.state import Extraction
from avengers_bank.core.clock import KST, now_utc, set_demo_hour
from avengers_bank.core.config import get_settings
from tests.conftest import new_chat_session, open_checking

pytestmark = pytest.mark.anyio


@pytest.fixture
def demo_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_mode", True)
    yield
    set_demo_hour(None)


async def test_clock_is_hidden_without_demo_mode(client):
    response = await client.post("/demo/clock", json={"kst_hour": 2})
    assert response.status_code == 404
    status = (await client.get("/demo/status")).json()["data"]
    assert (status["demo_mode"], status["shifted"]) == (False, False)


async def test_clock_moves_forward_to_hour(client, demo_mode):
    before = now_utc()
    response = await client.post("/demo/clock", json={"kst_hour": 2})
    data = response.json()["data"]
    assert data["shifted"] is True
    assert now_utc().astimezone(KST).hour == 2
    assert now_utc() > before  # 과거로는 옮기지 않는다

    await client.post("/demo/clock", json={"kst_hour": None})
    assert (await client.get("/demo/status")).json()["data"]["shifted"] is False


async def test_night_rule_and_tokens_work_when_shifted(client, user, other_user, demo_mode, monkeypatch):
    """새벽 2시로 옮기면 심야 고액 규칙이 걸리고, 확인 카드(JWT)는 실제 시각 기준이라 그대로 쓸 수 있다."""
    mine = await open_checking(client, user, balance=5_000_000)
    mom = await open_checking(client, other_user)
    await client.post("/recipients", headers=user, json={"account_num": mom["account_num"], "nickname": "엄마"})
    await client.post("/demo/clock", json={"kst_hour": 2})

    async def classify(history, user_text, pending):
        return Extraction(intent="transfer", recipient="엄마", amount=600_000)

    monkeypatch.setattr(llm, "classify", classify)
    session_id = await new_chat_session(client, user)
    response = await client.post(f"/chat/sessions/{session_id}/messages", headers=user, json={"text": "엄마한테 60만원 보내줘"})
    card = response.json()["data"]["assistant_message"]["card"]

    response = await client.post("/transfers", headers=user, json={
        "from_checking_account_id": mine["account_id"], "to_account_num": card["to_account_num"], "amount": 600_000,
        "session_id": session_id, "confirmation_token": card["confirmation_token"],
    })
    error = response.json()["error"]
    assert error["code"] == "ADDITIONAL_AUTH_REQUIRED"  # 토큰은 유효했고, FDS가 심야 규칙으로 막았다
    assert [h["code"] for h in error["extra"]["rule_hits"]] == ["NIGHT_HIGH_AMOUNT"]
