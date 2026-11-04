"""AUI 에이전트 그래프 (LangGraph).

    classify ─┬─ transfer ─────────────── END   이체: 슬롯 채우기 → 확인 카드 (코드로 처리, 실행 안 함)
              ├─ cancel ───────────────── END
              └─ agent ⇄ tools ────────── END   조회·상품·카드·일반 대화: LLM이 조회 도구를 골라 호출

이체를 LLM의 자유로운 도구 호출에 맡기지 않는 이유: 받는 사람·금액·계좌를 틀리면 곧 돈 문제다.
LLM은 의도와 슬롯 추출만 하고, 금액 재검증·수취인 조회·카드 생성은 정해진 코드가 한다.
"""

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from avengers_bank.agents import llm
from avengers_bank.agents.prompts import SYSTEM_PROMPT
from avengers_bank.agents.state import AgentState, PendingTransfer
from avengers_bank.agents.tools import (
    PrepareTransferArgs,
    ToolContext,
    build_read_tools,
    find_holder,
    find_recipient,
    my_checking_accounts,
    prepare_transfer,
)
from avengers_bank.domains.chat.amount import format_korean_amount, normalize_amount

MAX_TOOL_ROUNDS = 4
FALLBACK_REPLY = "죄송해요, 제가 잘 이해하지 못했어요. 다시 한 번 말씀해 주시겠어요?"


def _ask(slots: PendingTransfer, message: str) -> dict:
    """이체 정보가 모자라서 되묻는다. 이전 확인 카드는 무효로 한다."""
    return {"reply": message, "card": None, "new_pending": slots, "confirmation_jti": None}


async def handle_transfer(ctx: ToolContext, state: AgentState) -> dict:
    ex = state["extraction"]
    text = state["user_text"]
    slots = (state.get("pending") or PendingTransfer()).model_copy()

    # 1. 받는 사람: 계좌번호를 직접 말했으면 그것, 아니면 별칭으로 수취인 찾기
    if ex.to_account_num and ex.to_account_num != slots.to_account_num:
        holder = await find_holder(ctx, ex.to_account_num)
        if holder is None:
            return _ask(slots, "말씀하신 계좌를 찾을 수 없어요. 계좌번호를 다시 확인해 주세요.")
        slots.to_account_num, slots.holder_name, slots.recipient_nickname = ex.to_account_num, holder, None
    elif ex.recipient and ex.recipient != slots.recipient_nickname:
        found = await find_recipient(ctx, ex.recipient)
        if found is None:
            slots.to_account_num = slots.holder_name = slots.recipient_nickname = None
            return _ask(slots, f'"{ex.recipient}"(으)로 등록된 분이 없어요. 받는 분의 계좌번호를 알려 주세요.')
        slots.recipient_nickname = found["nickname"]
        slots.to_account_num, slots.holder_name = found["account_num"], found["holder_name"]

    # 2. 금액: LLM이 뽑은 값과 정규식으로 다시 계산한 값이 같아야 받아들인다
    heard = normalize_amount(text)
    if ex.amount is not None and ex.amount != slots.amount:
        if heard != ex.amount:
            slots.amount = None
            return _ask(slots, "금액을 정확히 확인하고 싶어요. 보낼 금액을 \"5만원\"처럼 다시 말씀해 주세요.")
        slots.amount = heard
    elif ex.amount is None and heard is not None:
        slots.amount = heard

    # 3. 출금 계좌: 입출금 계좌가 하나면 그것, 여러 개면 별칭으로 고르거나 묻는다
    checking = await my_checking_accounts(ctx)
    if not checking:
        return {"reply": "보낼 수 있는 입출금 계좌가 없어요. 먼저 입출금 계좌를 만들어 주세요.",
                "card": None, "new_pending": None, "confirmation_jti": None}
    ids = {a.account_id for a in checking}
    if slots.from_checking_account_id not in ids:
        slots.from_checking_account_id = None
    if ex.from_account_hint:
        hint = ex.from_account_hint.replace("통장", "").replace("계좌", "").strip()
        matched = [a for a in checking if hint and a.nickname and (hint in a.nickname or a.nickname in hint)]
        if len(matched) == 1:
            slots.from_checking_account_id = matched[0].account_id
    if slots.from_checking_account_id is None and len(checking) == 1:
        slots.from_checking_account_id = checking[0].account_id

    # 4. 빠진 것을 하나씩 묻는다
    who = slots.recipient_nickname or slots.holder_name
    if slots.to_account_num is None:
        return _ask(slots, "누구에게 보낼까요? 등록된 이름(예: 엄마)이나 계좌번호를 말씀해 주세요.")
    if slots.amount is None:
        return _ask(slots, f"{who}님께 얼마를 보낼까요?")
    if slots.from_checking_account_id is None:
        names = ", ".join(a.nickname or f"끝자리 {a.account_num[-4:]}" for a in checking)
        return _ask(slots, f"어느 계좌에서 보낼까요? ({names})")

    # 5. 확인 카드 (실행은 사용자가 카드에서 승인할 때)
    card, jti = await prepare_transfer(ctx, PrepareTransferArgs(
        from_checking_account_id=slots.from_checking_account_id,
        to_account_num=slots.to_account_num,
        holder_name=slots.holder_name,
        recipient_nickname=slots.recipient_nickname,
        amount=slots.amount,
    ))
    name = f"{slots.recipient_nickname}({slots.holder_name})" if slots.recipient_nickname else slots.holder_name
    reply = f"{name}님께 {format_korean_amount(slots.amount)}을 보낼까요? 화면의 확인 카드에서 승인을 눌러 주세요."
    if card["insufficient_balance"]:
        reply = f"출금 계좌 잔액이 {format_korean_amount(card['from_balance'])}이라 부족해요. " + reply
    return {"reply": reply, "card": card, "new_pending": slots, "confirmation_jti": jti}


def build_graph(ctx: ToolContext):
    tools = build_read_tools(ctx)
    tools_by_name = {tool.name: tool for tool in tools}

    async def classify_node(state: AgentState) -> dict:
        extraction = await llm.classify(state.get("history", []), state["user_text"], state.get("pending"))
        return {"extraction": extraction}

    def route(state: AgentState) -> str:
        intent = state["extraction"].intent
        return intent if intent in ("transfer", "cancel") else "agent"

    async def transfer_node(state: AgentState) -> dict:
        return await handle_transfer(ctx, state)

    async def cancel_node(state: AgentState) -> dict:
        reply = "이체를 취소했어요." if state.get("pending") else "진행 중인 이체가 없어요."
        return {"reply": reply, "card": None, "new_pending": None, "confirmation_jti": None}

    async def agent_node(state: AgentState) -> dict:
        messages = state.get("messages") or [
            SystemMessage(SYSTEM_PROMPT), *state.get("history", []), HumanMessage(state["user_text"])
        ]
        response = await llm.get_chat_llm().bind_tools(tools).ainvoke(messages)
        update = {"messages": [*messages, response], "new_pending": state.get("pending")}
        if not response.tool_calls or state.get("tool_rounds", 0) >= MAX_TOOL_ROUNDS:
            update["reply"] = response.text or FALLBACK_REPLY
        return update

    def after_agent(state: AgentState) -> str:
        return END if "reply" in state else "tools"

    async def tools_node(state: AgentState) -> dict:
        # 같은 DB 세션을 쓰므로 도구는 병렬이 아니라 하나씩 실행한다
        last: AIMessage = state["messages"][-1]
        results, card = [], state.get("card")
        for call in last.tool_calls:
            tool = tools_by_name.get(call["name"])
            if tool is None:
                output = json.dumps({"error": "없는 도구입니다."}, ensure_ascii=False)
            else:
                try:
                    output = await tool.ainvoke(call["args"])
                except Exception:  # 잘못된 인자 등. 오류 내용은 LLM에 넘기지 않는다
                    output = json.dumps({"error": "조회에 실패했습니다."}, ensure_ascii=False)
            if call["name"] == "get_my_accounts" and not output.startswith('{"error"'):
                card = {"type": "account_summary", "accounts": json.loads(output)}
            results.append(ToolMessage(content=output, tool_call_id=call["id"], name=call["name"]))
        return {"messages": [*state["messages"], *results], "card": card,
                "tool_rounds": state.get("tool_rounds", 0) + 1}

    graph = StateGraph(AgentState)
    graph.add_node("classify", classify_node)
    graph.add_node("transfer", transfer_node)
    graph.add_node("cancel", cancel_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", route, ["transfer", "cancel", "agent"])
    graph.add_edge("transfer", END)
    graph.add_edge("cancel", END)
    graph.add_conditional_edges("agent", after_agent, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()
