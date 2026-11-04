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
    assert reply["screen"] == "transfer"

    response = await client.post("/transfers", headers=user, json=approve(card, bank["session_id"]))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["balance_after"] == 950_000

    # 같은 카드로 두 번 보낼 수 없다
    response = await client.post("/transfers", headers=user, json=approve(card, bank["session_id"]))
    assert response.json()["error"]["code"] == "CONFIRMATION_USED"

    messages = (await client.get(f"/chat/sessions/{bank['session_id']}/messages", headers=user)).json()["data"]
    assert [(m["role"], m["intent"], m["input_mode"], m["screen"]) for m in messages] == [
        ("user", "transfer", "voice", None), ("assistant", None, "text", "transfer")
    ]


async def test_asks_for_missing_amount(client, user, bank, classify):
    classify.next(intent="transfer", recipient="엄마")
    reply = await say(client, user, bank["session_id"], "엄마한테 돈 좀 보내줘")
    assert reply["card"] is None
    assert reply["screen"] is None  # 되묻는 동안은 화면을 바꾸지 않는다
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
    # 계좌를 말하지 않으면 가장 먼저 만든 계좌(생활비)에서, 어느 계좌인지 밝힌다
    assert reply["card"]["from_nickname"] == "생활비"
    assert reply["content"].startswith("생활비 통장에서")

    classify.next(intent="transfer", from_account_hint="월급통장")
    reply = await say(client, user, bank["session_id"], "월급통장에서")
    assert reply["card"]["from_nickname"] == "월급"


async def test_cancel_clears_pending(client, user, bank, classify):
    classify.next(intent="transfer", recipient="엄마")
    await say(client, user, bank["session_id"], "엄마한테 보내줘")
    classify.next(intent="cancel")
    reply = await say(client, user, bank["session_id"], "아니 됐어")
    assert reply["content"] == "이체를 취소했어요."
    assert reply["screen"] == "home"

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


async def test_llm_conversation_judgment_blocks_transfer(client, user, bank, classify, chat_model, monkeypatch):
    """키워드가 없어도 LLM이 대화를 보이스피싱으로 보면 차단하고, 근거를 돌려준다"""
    from avengers_bank.domains.fds import conversation

    seen = []

    async def judge(texts):
        seen.append(texts)
        return conversation.ConversationRisk(risk="scam", reason="가족을 사칭해 급히 송금을 요구하고 있어요.")

    monkeypatch.setattr(conversation, "judge", judge)
    classify.next(intent="general")
    chat_model(AIMessage("가족 사칭일 수 있어요. 직접 전화로 확인해 보세요."))
    await say(client, user, bank["session_id"], "딸이 폰이 고장났다고 새 번호로 문자 왔는데 급하대")

    classify.next(intent="transfer", recipient="엄마", amount=50_000)
    card = (await say(client, user, bank["session_id"], "엄마한테 5만원 보내줘"))["card"]
    response = await client.post("/transfers", headers=user, json=approve(card, bank["session_id"]))
    error = response.json()["error"]
    assert error["code"] == "FDS_BLOCKED"
    assert {"code": "CONVERSATION_AI_SCAM", "name": "AI가 대화를 보이스피싱으로 판단", "level": "HIGH",
            "detail": "가족을 사칭해 급히 송금을 요구하고 있어요."} in error["extra"]["rule_hits"]
    assert seen[-1][0].startswith("딸이 폰이")  # 같은 세션 사용자 글을 오래된 것부터 넘긴다

    logs = (await client.get("/fds/logs", headers=user)).json()["data"]
    assert logs[0]["rule_hits"][0]["detail"] == "가족을 사칭해 급히 송금을 요구하고 있어요."


async def test_inquiry_uses_tools_and_returns_summary_card(client, user, bank, classify, chat_model):
    classify.next(intent="inquiry")
    model = chat_model(
        AIMessage("", tool_calls=[{"name": "get_my_accounts", "args": {}, "id": "call-1"}]),
        AIMessage("생활비 통장에 100만원 있어요."),
    )
    reply = await say(client, user, bank["session_id"], "내 잔액 얼마야?")
    assert reply["content"] == "생활비 통장에 100만원 있어요."
    assert reply["card"]["type"] == "account_summary"
    assert reply["screen"] == "accounts"
    [account] = reply["card"]["accounts"]
    assert account["balance"] == 1_000_000
    assert account["account_num"].startswith("****")  # LLM에는 뒤 4자리만

    # 도구는 MCP 서버에서 오고, 이체 카드·수취인 등록 같은 도구는 LLM에게 주지 않는다
    assert {"get_my_accounts", "search_products", "get_my_cards", "get_fds_logs"} <= set(model.tool_names)
    assert not LLM_EXCLUDED & set(model.tool_names)
    tool_message = model.calls[1][-1]
    assert tool_message.name == "get_my_accounts"


async def test_screen_follows_last_tool(client, user, bank, classify, chat_model):
    """도구를 여러 개 쓰면 마지막 도구의 화면, 도구 없이 답하면 화면을 바꾸지 않는다"""
    classify.next(intent="product")
    chat_model(
        AIMessage("", tool_calls=[{"name": "get_my_accounts", "args": {}, "id": "call-1"}]),
        AIMessage("", tool_calls=[{"name": "search_products", "args": {"kind": "account"}, "id": "call-2"}]),
        AIMessage("잔액에 맞는 적금을 찾아봤어요."),
    )
    reply = await say(client, user, bank["session_id"], "내 잔액으로 들 만한 적금 있어?")
    assert (reply["screen"], reply["screen_params"]) == ("products", {"kind": "account"})

    classify.next(intent="card")
    chat_model(AIMessage("체크카드를 만들어 드릴까요?"))
    reply = await say(client, user, bank["session_id"], "카드 하나 만들어줘")
    assert reply["screen"] is None  # 동의를 묻는 턴은 도구를 쓰지 않는다


async def test_screen_carries_target(client, user, other_user, bank, classify, chat_model):
    """"생활비 통장 거래내역" → 계좌 목록이 아니라 그 계좌 화면. 남의 계좌라 도구가 실패하면 화면을 바꾸지 않는다"""
    mine = bank["mine"]
    classify.next(intent="inquiry")
    chat_model(
        AIMessage("", tool_calls=[{"name": "get_account_histories", "args": {
            "account_type": "checking", "account_id": mine["account_id"]}, "id": "call-1"}]),
        AIMessage("생활비 통장 최근 거래예요."),
    )
    reply = await say(client, user, bank["session_id"], "생활비 통장 거래내역 보여줘")
    assert (reply["screen"], reply["screen_params"]) == (
        "account", {"account_type": "checking", "account_id": mine["account_id"]}
    )

    classify.next(intent="inquiry")
    chat_model(
        AIMessage("", tool_calls=[{"name": "get_account", "args": {
            "account_type": "checking", "account_id": bank["mom"]["account_id"]}, "id": "call-2"}]),
        AIMessage("그 계좌는 볼 수 없어요."),
    )
    reply = await say(client, user, bank["session_id"], "엄마 계좌 잔액 알려줘")
    assert reply["screen"] is None and reply["screen_params"] is None

    messages = (await client.get(f"/chat/sessions/{bank['session_id']}/messages", headers=user)).json()["data"]
    assert messages[1]["screen_params"]["account_id"] == mine["account_id"]  # 새로고침해도 복원할 수 있게 저장


def test_screen_for_tools():
    from avengers_bank.agents.graph import screen_for

    assert screen_for("issue_debit_card", {"product_id": 2, "checking_account_id": 1}, {"card_type": "debit", "card_id": 7}) == (
        "card", {"card_type": "debit", "card_id": 7}
    )
    assert screen_for("open_savings_account", {}, {"account_type": "savings", "account_id": 3}) == (
        "account", {"account_type": "savings", "account_id": 3}
    )
    # 한도 높이기는 거절돼도 그 계좌 화면으로 (거기서 PIN으로 높인다)
    assert screen_for("lower_transfer_limits", {"checking_account_id": 5}, {"error": "LIMIT_RAISE_NOT_ALLOWED"}) == (
        "account", {"account_type": "checking", "account_id": 5}
    )
    assert screen_for("get_product", {"kind": "card", "product_id": 2}, {}) == ("products", {"kind": "card", "product_id": 2})
    assert screen_for("search_products", {"kind": "all"}, {}) == ("products", {"kind": "all"})
    assert screen_for("find_recipient", {"nickname": "엄마"}, {}) is None


async def test_ui_context_reaches_agent_but_not_history(client, user, bank, classify, chat_model):
    """모아 화면이 보낸 "지금 화면"은 에이전트에게만 붙고, 대화 기록에는 사용자가 쓴 글만 남는다"""
    classify.next(intent="product")
    model = chat_model(AIMessage("어벤져스 데일리 체크카드를 만들어 드릴까요?"))
    ui = {
        "screen": "products", "screen_params": {"kind": "card"},
        "visible": ["어벤져스 플래티넘 신용카드", "어벤져스 데일리 체크카드"],
        "selected": {"kind": "product", "label": "어벤져스 데일리 체크카드", "product_kind": "card", "product_id": 2},
    }
    await say(client, user, bank["session_id"], "이거 가입해줘", ui_context=ui)

    sent = model.calls[0][-1].content
    assert sent.startswith("이거 가입해줘\n\n[지금 사용자 화면")
    assert "상품 목록 (kind=card)" in sent
    assert "2. 어벤져스 데일리 체크카드" in sent
    assert 'product "어벤져스 데일리 체크카드" product_kind=card, product_id=2' in sent

    messages = (await client.get(f"/chat/sessions/{bank['session_id']}/messages", headers=user)).json()["data"]
    assert messages[0]["content"] == "이거 가입해줘"

    # 화면 정보가 없으면 붙이지 않는다 (채팅 화면)
    classify.next(intent="general")
    model = chat_model(AIMessage("네, 말씀하세요."))
    await say(client, user, bank["session_id"], "안녕")
    assert model.calls[0][-1].content == "안녕"


async def test_ui_context_is_validated(client, user, bank):
    """클라이언트가 보내는 값이므로 모양·길이를 막는다"""
    path = f"/chat/sessions/{bank['session_id']}/messages"
    bad = [
        {"screen": "admin"},
        {"visible": ["x"] * 11},
        {"visible": ["가" * 61]},
        {"selected": {"kind": "product", "label": "x", "product_id": "1; drop"}},
        {"screen_params": {f"k{i}": i for i in range(6)}},
    ]
    for ui in bad:
        response = await client.post(path, headers=user, json={"text": "이거", "ui_context": ui})
        assert response.status_code == 422, ui


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
