"""에이전트 대화 테스트. Gemini는 부르지 않고 분류기·대화 모델을 가짜로 바꾼다."""

import pytest
from langchain_core.messages import AIMessage

from avengers_bank.agents import llm
from avengers_bank.agents.mcp_client import LLM_EXCLUDED
from avengers_bank.agents.state import Extraction
from tests.conftest import new_chat_session, open_checking, signup_and_login

pytestmark = pytest.mark.anyio


class FakeChatModel:
    """bind_tools 후 ainvoke하면 준비한 응답을 차례로 돌려준다."""

    def __init__(self, *responses: AIMessage):
        self.responses = list(responses)
        self.calls = []

    def bind_tools(self, tools):
        self.tool_names = [t.name for t in tools]
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


@pytest.fixture
def classify(monkeypatch):
    """classify.next(...)로 다음 분류 결과를 정한다."""

    class Classifier:
        queue: list[Extraction] = []
        seen: list[tuple] = []

        def next(self, **kwargs):
            self.queue.append(Extraction(**kwargs))

        async def __call__(self, history, user_text, pending):
            self.seen.append((user_text, pending))
            return self.queue.pop(0)

    classifier = Classifier()
    classifier.queue, classifier.seen = [], []
    monkeypatch.setattr(llm, "classify", classifier)
    return classifier


@pytest.fixture
def chat_model(monkeypatch):
    holder = {}

    def use(*responses):
        holder["model"] = FakeChatModel(*responses)
        return holder["model"]

    monkeypatch.setattr(llm, "get_chat_llm", lambda: holder["model"])
    return use


@pytest.fixture
async def bank(client, user, other_user):
    """나: 입출금 계좌(잔액 100만원), 엄마(other_user) 계좌를 "엄마"로 등록"""
    mine = await open_checking(client, user, balance=1_000_000, nickname="생활비")
    mom = await open_checking(client, other_user)
    await client.post("/recipients", headers=user, json={"account_num": mom["account_num"], "nickname": "엄마"})
    session_id = await new_chat_session(client, user)
    return {"mine": mine, "mom": mom, "session_id": session_id}


async def say(client, headers, session_id, text, **extra):
    response = await client.post(
        f"/chat/sessions/{session_id}/messages", headers=headers, json={"text": text, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["assistant_message"]


def approve(card: dict, session_id: str, **extra) -> dict:
    """프론트가 확인 카드의 승인 버튼을 눌렀을 때 보내는 요청"""
    return {
        "from_checking_account_id": card["from_checking_account_id"],
        "to_account_num": card["to_account_num"],
        "amount": card["amount"],
        "session_id": session_id,
        "confirmation_token": card["confirmation_token"],
        **extra,
    }


async def test_send_to_mom_scenario(client, user, other_user, bank, classify):
    """엄마한테 5만원 보내줘 → 확인 카드 → 승인 → 이체 완료"""
    classify.next(intent="transfer", recipient="엄마", amount=50_000, amount_text="오만원")
    reply = await say(client, user, bank["session_id"], "엄마한테 오만원 보내줘", input_mode="voice")

    card = reply["card"]
    assert card["type"] == "transfer_confirmation"
    assert (card["to_account_num"], card["amount"], card["holder_name"]) == (bank["mom"]["account_num"], 50_000, "브루스 배너")
    assert card["tts_text"] == "엄마님께 5만원을 보냅니다. 승인하시겠어요?"
    assert "110-" not in card["tts_text"]  # 계좌번호는 읽지 않는다
    assert "5만원" in reply["content"]

    response = await client.post("/transfers", headers=user, json=approve(card, bank["session_id"]))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["balance_after"] == 950_000

    # 같은 카드로 두 번 보낼 수 없다
    response = await client.post("/transfers", headers=user, json=approve(card, bank["session_id"]))
    assert response.json()["error"]["code"] == "CONFIRMATION_USED"

    messages = (await client.get(f"/chat/sessions/{bank['session_id']}/messages", headers=user)).json()["data"]
    assert [(m["role"], m["intent"], m["input_mode"]) for m in messages] == [
        ("user", "transfer", "voice"), ("assistant", None, "text")
    ]


async def test_asks_for_missing_amount(client, user, bank, classify):
    classify.next(intent="transfer", recipient="엄마")
    reply = await say(client, user, bank["session_id"], "엄마한테 돈 좀 보내줘")
    assert reply["card"] is None
    assert reply["content"] == "엄마님께 얼마를 보낼까요?"

    classify.next(intent="transfer", amount=50_000)
    reply = await say(client, user, bank["session_id"], "5만원")
    assert reply["card"]["amount"] == 50_000
    assert reply["card"]["recipient_nickname"] == "엄마"
    # 두 번째 분류 때 진행 중인 이체(엄마)가 넘어갔다
    assert classify.seen[1][1].recipient_nickname == "엄마"


async def test_amount_mismatch_asks_again(client, user, bank, classify):
    """LLM이 50만원으로 잘못 들었지만 문장은 오만원 → 카드 없이 다시 묻는다"""
    classify.next(intent="transfer", recipient="엄마", amount=500_000)
    reply = await say(client, user, bank["session_id"], "엄마한테 오만원 보내줘")
    assert reply["card"] is None
    assert "다시 말씀해" in reply["content"]


async def test_unknown_recipient(client, user, bank, classify):
    classify.next(intent="transfer", recipient="삼촌", amount=10_000)
    reply = await say(client, user, bank["session_id"], "삼촌한테 만원 보내줘")
    assert reply["card"] is None
    assert "등록된 분이 없어요" in reply["content"]


async def test_choose_from_account_when_several(client, user, bank, classify):
    await open_checking(client, user, balance=500_000, nickname="월급")
    classify.next(intent="transfer", recipient="엄마", amount=30_000)
    reply = await say(client, user, bank["session_id"], "엄마한테 3만원 보내줘")
    assert reply["content"].startswith("어느 계좌에서 보낼까요?")
    assert "생활비" in reply["content"] and "월급" in reply["content"]

    classify.next(intent="transfer", from_account_hint="월급통장")
    reply = await say(client, user, bank["session_id"], "월급통장에서")
    assert reply["card"]["from_nickname"] == "월급"


async def test_cancel_clears_pending(client, user, bank, classify):
    classify.next(intent="transfer", recipient="엄마")
    await say(client, user, bank["session_id"], "엄마한테 보내줘")
    classify.next(intent="cancel")
    reply = await say(client, user, bank["session_id"], "아니 됐어")
    assert reply["content"] == "이체를 취소했어요."

    classify.next(intent="transfer", amount=10_000)
    reply = await say(client, user, bank["session_id"], "만원")
    assert reply["content"].startswith("누구에게 보낼까요?")


async def test_new_card_invalidates_old_one(client, user, bank, classify):
    classify.next(intent="transfer", recipient="엄마", amount=50_000)
    old = (await say(client, user, bank["session_id"], "엄마한테 5만원"))["card"]
    classify.next(intent="transfer", amount=100_000)
    new = (await say(client, user, bank["session_id"], "아니 10만원으로"))["card"]
    assert new["amount"] == 100_000

    response = await client.post("/transfers", headers=user, json=approve(old, bank["session_id"]))
    assert response.json()["error"]["code"] == "CONFIRMATION_USED"
    response = await client.post("/transfers", headers=user, json=approve(new, bank["session_id"]))
    assert response.status_code == 200


async def test_tampered_or_missing_token(client, user, bank, classify):
    classify.next(intent="transfer", recipient="엄마", amount=50_000)
    card = (await say(client, user, bank["session_id"], "엄마한테 5만원"))["card"]

    response = await client.post("/transfers", headers=user, json=approve(card, bank["session_id"], amount=500_000))
    assert response.json()["error"]["code"] == "CONFIRMATION_MISMATCH"

    body = approve(card, bank["session_id"])
    del body["confirmation_token"]
    response = await client.post("/transfers", headers=user, json=body)
    assert response.json()["error"]["code"] == "CONFIRMATION_REQUIRED"


async def test_phishing_keywords_in_chat_trigger_fds(client, user, bank, classify, chat_model):
    """대화에 보이스피싱 표현이 있으면 같은 세션의 이체가 대화 키워드 규칙에 걸린다"""
    classify.next(intent="general")
    chat_model(AIMessage("그런 전화는 보이스피싱일 수 있어요. 112에 확인해 보세요."))
    await say(client, user, bank["session_id"], "검찰청이라는데 안전계좌로 옮기래요")

    classify.next(intent="transfer", recipient="엄마", amount=50_000)
    card = (await say(client, user, bank["session_id"], "엄마한테 5만원 보내줘"))["card"]
    response = await client.post("/transfers", headers=user, json=approve(card, bank["session_id"]))
    error = response.json()["error"]
    assert error["code"] == "ADDITIONAL_AUTH_REQUIRED"
    assert "CONVERSATION_KEYWORD" in [h["code"] for h in error["extra"]["rule_hits"]]


async def test_inquiry_uses_tools_and_returns_summary_card(client, user, bank, classify, chat_model):
    classify.next(intent="inquiry")
    model = chat_model(
        AIMessage("", tool_calls=[{"name": "get_my_accounts", "args": {}, "id": "call-1"}]),
        AIMessage("생활비 통장에 100만원 있어요."),
    )
    reply = await say(client, user, bank["session_id"], "내 잔액 얼마야?")
    assert reply["content"] == "생활비 통장에 100만원 있어요."
    assert reply["card"]["type"] == "account_summary"
    [account] = reply["card"]["accounts"]
    assert account["balance"] == 1_000_000
    assert account["account_num"].startswith("****")  # LLM에는 뒤 4자리만

    # 도구는 MCP 서버에서 오고, 이체 카드·수취인 등록 같은 도구는 LLM에게 주지 않는다
    assert {"get_my_accounts", "search_products", "get_my_cards", "get_fds_logs"} <= set(model.tool_names)
    assert not LLM_EXCLUDED & set(model.tool_names)
    tool_message = model.calls[1][-1]
    assert tool_message.name == "get_my_accounts"


async def test_others_session_is_hidden(client, user, bank):
    stranger = await signup_and_login(client, "thor", "토르")
    response = await client.get(f"/chat/sessions/{bank['session_id']}/messages", headers=stranger)
    assert response.status_code == 403
    response = await client.post(
        f"/chat/sessions/{bank['session_id']}/messages", headers=stranger, json={"text": "안녕"}
    )
    assert response.status_code == 403


async def test_llm_failure_returns_503(client, user, bank, monkeypatch):
    async def broken(*args):
        raise RuntimeError("network down")

    monkeypatch.setattr(llm, "classify", broken)
    response = await client.post(
        f"/chat/sessions/{bank['session_id']}/messages", headers=user, json={"text": "안녕"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"
