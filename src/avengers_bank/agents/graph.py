"""AUI 에이전트 그래프 (LangGraph). 은행 기능은 모두 MCP 서버(mcp_servers/)의 도구로 쓴다.

    classify ─┬─ transfer ─────────────── END   이체: 슬롯 채우기 → MCP prepare_transfer로 확인 카드 (실행 안 함)
              ├─ cancel ───────────────── END
              └─ agent ⇄ tools ────────── END   조회·상품·카드·일반 대화: LLM이 MCP 도구를 골라 호출

이체를 LLM의 자유로운 도구 호출에 맡기지 않는 이유: 받는 사람·금액·계좌를 틀리면 곧 돈 문제다.
LLM은 의도와 슬롯 추출만 하고, 금액 재검증·수취인 조회·카드 생성은 정해진 순서로 MCP 도구를 부르는 코드가 한다.
"""

import json
from dataclasses import dataclass

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from avengers_bank.agents import llm
from avengers_bank.agents.mcp_client import BankMcpClient
from avengers_bank.agents.prompts import SYSTEM_PROMPT
from avengers_bank.agents.state import AgentState, PendingTransfer, Screen
from avengers_bank.agents.ui_context import with_ui
from avengers_bank.domains.chat.amount import format_korean_amount, normalize_amount

MAX_TOOL_ROUNDS = 4
FALLBACK_REPLY = "죄송해요, 제가 잘 이해하지 못했어요. 다시 한 번 말씀해 주시겠어요?"

OPEN_ACCOUNT_TYPES = {"open_checking_account": "checking", "open_deposit_account": "deposit", "open_savings_account": "savings"}
ISSUE_CARD_TYPES = {"issue_debit_card": "debit", "issue_credit_card": "credit"}


def screen_for(name: str, args: dict, result: dict) -> tuple[Screen, dict] | None:
    """도구 호출 → 그 결과를 보여 줄 화면과 대상·조건. None이면 화면을 바꾸지 않는다.

    "생활비 통장 거래내역"이면 계좌 목록이 아니라 그 계좌 화면을 가져오도록, LLM이 도구에 넘긴 인자를 그대로 쓴다.
    개설·발급은 결과에 담긴 새 계좌·카드 화면으로 간다 (동의를 묻는 턴은 도구를 안 쓰므로 화면이 안 바뀐다).
    도구가 실패하면 화면을 바꾸지 않는다. 한도 높이기 거절만 예외: 그 계좌 화면에서 PIN으로 높일 수 있게 가져간다.
    """
    if "error" in result and result["error"] != "LIMIT_RAISE_NOT_ALLOWED":
        return None
    match name:
        case "get_my_accounts":
            return "accounts", {}
        case "get_account" | "get_account_histories" | "rename_account":
            return "account", {"account_type": args["account_type"], "account_id": args["account_id"]}
        case "lower_transfer_limits":
            return "account", {"account_type": "checking", "account_id": args["checking_account_id"]}
        case _ if name in OPEN_ACCOUNT_TYPES:
            return "account", {"account_type": OPEN_ACCOUNT_TYPES[name], "account_id": result["account_id"]}
        case "get_my_cards":
            return "cards", {}
        case "get_card_histories":
            return "card", {"card_type": args["card_type"], "card_id": args["card_id"]}
        case _ if name in ISSUE_CARD_TYPES:
            return "card", {"card_type": ISSUE_CARD_TYPES[name], "card_id": result["card_id"]}
        case "search_products":
            return "products", {k: v for k, v in {"kind": args.get("kind"), "keyword": args.get("keyword")}.items() if v}
        case "get_product":
            return "products", {"kind": args["kind"], "product_id": args["product_id"]}
        case "get_fds_logs":
            return "fds", {}
    return None


@dataclass
class AgentContext:
    session_id: str
    mcp: BankMcpClient
    _tools: list[BaseTool] | None = None

    async def tools(self) -> list[BaseTool]:
        """LLM에게 주는 MCP 도구. 조회·상담 경로에서 처음 필요할 때 한 번 받아 온다."""
        if self._tools is None:
            self._tools = await self.mcp.llm_tools()
        return self._tools


def _ask(slots: PendingTransfer, message: str) -> dict:
    """이체 정보가 모자라서 되묻는다. 이전 확인 카드는 무효로 한다."""
    return {"reply": message, "card": None, "new_pending": slots, "confirmation_jti": None}


ACCOUNT_KIND_WORDS = {"checking": ("입출금",), "savings": ("적금",), "deposit": ("예금",)}


def find_own_account(words: str, accounts: list[dict]) -> dict | None:
    """받는 쪽으로 말한 표현("월급 통장", "적금", "내 예금")이 내 계좌 하나를 가리키면 그 계좌.
    별칭이 맞으면 그것, 아니면 종류(적금·예금·입출금)로 하나뿐일 때만. 여러 개면 None (되묻는다)."""
    key = words.replace(" ", "")
    for word in ("내", "통장", "계좌", "으로", "로", "에"):
        key = key.replace(word, "") if word != "내" else key.removeprefix("내")
    if not key:
        return None
    by_name = [a for a in accounts if a.get("nickname") and (key in a["nickname"].replace(" ", "") or a["nickname"].replace(" ", "") in key)]
    if len(by_name) == 1:
        return by_name[0]
    by_kind = [a for a in accounts if any(k in key for k in ACCOUNT_KIND_WORDS[a["account_type"]])]
    return by_kind[0] if len(by_kind) == 1 else None


def tool_text(output) -> str:
    """MCP 도구 결과(문자열 또는 content block 목록) → 문자열"""
    if isinstance(output, str):
        return output
    return "".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in output)


async def handle_transfer(ctx: AgentContext, state: AgentState) -> dict:
    ex = state["extraction"]
    text = state["user_text"]
    slots = (state.get("pending") or PendingTransfer()).model_copy()

    accounts = (await ctx.mcp.call("accounts", "get_my_accounts", {})).get("accounts", [])

    # 1. 받는 사람: 계좌번호를 직접 말했으면 그 예금주, 내 계좌 별칭("월급 통장으로")이면 내 계좌, 아니면 수취인 별칭
    own = find_own_account(ex.recipient, accounts) if ex.recipient else None
    kind_word = next((w for w in ("적금", "예금", "통장", "계좌") if ex.recipient and w in ex.recipient), None)
    if own is None and kind_word:
        # "적금에", "월급 통장으로"처럼 계좌를 가리켰는데 내 계좌 하나로 정해지지 않으면 사람 이름으로 찾지 않는다
        kinds = {"적금": ["savings"], "예금": ["deposit"]}.get(kind_word, ["checking", "savings", "deposit"])
        candidates = [a for a in accounts if a["account_type"] in kinds]
        if not candidates:
            return _ask(slots, f"{kind_word} 계좌가 없어요. 상품을 보고 먼저 가입해 주세요.")
        names = ", ".join(a["nickname"] or ACCOUNT_KIND_WORDS[a["account_type"]][0] for a in candidates)
        return _ask(slots, f"어느 계좌로 옮길까요? 내 계좌: {names}")
    if own is not None:
        slots.to_own_account_type, slots.to_own_account_id = own["account_type"], own["account_id"]
        slots.recipient_nickname = slots.to_account_num = slots.holder_name = None
    elif ex.to_account_num and ex.to_account_num != slots.to_account_num:
        found = await ctx.mcp.call("transfers", "find_account_holder", {"account_num": ex.to_account_num})
        if "error" in found:
            return _ask(slots, "말씀하신 계좌를 찾을 수 없어요. 계좌번호를 다시 확인해 주세요.")
        slots.to_account_num, slots.holder_name, slots.recipient_nickname = ex.to_account_num, found["holder_name"], None
        slots.to_own_account_type = slots.to_own_account_id = None
    elif ex.recipient and ex.recipient != slots.recipient_nickname:
        found = await ctx.mcp.call("transfers", "find_recipient", {"nickname": ex.recipient})
        if "error" in found:
            slots.to_account_num = slots.holder_name = slots.recipient_nickname = None
            return _ask(slots, f'"{ex.recipient}"(으)로 등록된 분이 없어요. 받는 분의 계좌번호를 알려 주세요.')
        slots.recipient_nickname, slots.holder_name, slots.to_account_num = found["nickname"], found["holder_name"], None
        slots.to_own_account_type = slots.to_own_account_id = None

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
    checking = [a for a in accounts if a["account_type"] == "checking"]
    if not checking:
        return {"reply": "보낼 수 있는 입출금 계좌가 없어요. 먼저 입출금 계좌를 만들어 주세요.",
                "card": None, "new_pending": None, "confirmation_jti": None}
    if slots.from_checking_account_id not in {a["account_id"] for a in checking}:
        slots.from_checking_account_id = None
    if ex.from_account_hint:
        hint = ex.from_account_hint.replace("통장", "").replace("계좌", "").strip()
        matched = [a for a in checking if hint and a["nickname"] and (hint in a["nickname"] or a["nickname"] in hint)]
        if len(matched) == 1:
            slots.from_checking_account_id = matched[0]["account_id"]
    # 내 입출금 계좌로 옮기는데 출금 계좌를 말하지 않았으면 받는 계좌가 아닌 쪽에서
    to_own_checking = slots.to_own_account_id if slots.to_own_account_type == "checking" else None
    if slots.from_checking_account_id is None or slots.from_checking_account_id == to_own_checking:
        others = [a["account_id"] for a in checking if a["account_id"] != to_own_checking]
        if not others:
            return _ask(slots, "같은 계좌로는 옮길 수 없어요. 어느 계좌에서 보낼지 말씀해 주세요.")
        # 말하지 않았으면 가장 먼저 만든 입출금 계좌(주 계좌). 카드와 답변에 계좌를 밝히고, "월급 통장에서"라고 하면 바꾼다
        slots.from_checking_account_id = min(others)

    # 4. 빠진 것을 하나씩 묻는다
    own_target = next((a for a in accounts if slots.to_own_account_id and a["account_id"] == slots.to_own_account_id
                       and a["account_type"] == slots.to_own_account_type), None)
    who = slots.recipient_nickname or slots.holder_name
    if not (slots.recipient_nickname or slots.to_account_num or own_target):
        return _ask(slots, "누구에게 보낼까요? 등록된 이름(예: 엄마)이나 계좌번호, 또는 내 계좌 이름(예: 월급 통장)을 말씀해 주세요.")
    if slots.amount is None:
        return _ask(slots, "얼마를 옮길까요?" if own_target else f"{who}님께 얼마를 보낼까요?")

    # 5. 확인 카드 (MCP prepare_transfer. 실행은 사용자가 카드에서 승인할 때)
    card = await ctx.mcp.call("transfers", "prepare_transfer", {
        "session_id": ctx.session_id,
        "from_checking_account_id": slots.from_checking_account_id,
        "amount": slots.amount,
        "recipient_nickname": slots.recipient_nickname,
        "to_account_num": None if slots.recipient_nickname or own_target else slots.to_account_num,
        "to_own_account_type": slots.to_own_account_type if own_target else None,
        "to_own_account_id": slots.to_own_account_id if own_target else None,
    })
    if "error" in card:
        return _ask(slots, card["message"])
    jti = card.pop("confirmation_jti")

    name = f"{slots.recipient_nickname}({slots.holder_name})" if slots.recipient_nickname else slots.holder_name
    if card["voice_challenge"]:
        how = f"맞으면 \"확인 {card['voice_challenge_text']}\"이라고 말씀해 주세요."
    elif card["voice_enrolled"]:
        how = "화면의 확인 카드에서 PIN으로 승인해 주세요."
    else:
        how = "화면의 확인 카드에서 승인을 눌러 주세요."
    source = f"{card['from_nickname']} 통장에서 " if len(checking) > 1 and card["from_nickname"] else ""
    if card["to_own"]:
        source = f"{card['from_nickname']} 통장에서 " if card["from_nickname"] else ""
        reply = f"{source}{card['to_label']}으로 {format_korean_amount(slots.amount)}을 옮길까요? {how}"
    else:
        reply = f"{source}{name}님께 {format_korean_amount(slots.amount)}을 보낼까요? {how}"
    if card["insufficient_balance"]:
        reply = f"출금 계좌 잔액이 {format_korean_amount(card['from_balance'])}이라 부족해요. " + reply
    return {"reply": reply, "card": card, "new_pending": slots, "confirmation_jti": jti}


def build_graph(ctx: AgentContext):
    async def classify_node(state: AgentState) -> dict:
        extraction = await llm.classify(state.get("history", []), state["user_text"], state.get("pending"))
        return {"extraction": extraction}

    def route(state: AgentState) -> str:
        intent = state["extraction"].intent
        return intent if intent in ("transfer", "cancel") else "agent"

    async def transfer_node(state: AgentState) -> dict:
        result = await handle_transfer(ctx, state)
        return {**result, "screen": "transfer" if result.get("card") else None, "screen_params": None}  # 되묻는 동안은 화면 그대로

    async def cancel_node(state: AgentState) -> dict:
        reply = "이체를 취소했어요." if state.get("pending") else "진행 중인 이체가 없어요."
        return {"reply": reply, "card": None, "new_pending": None, "confirmation_jti": None, "screen": "home", "screen_params": None}

    async def agent_node(state: AgentState) -> dict:
        messages = state.get("messages") or [
            SystemMessage(SYSTEM_PROMPT), *state.get("history", []),
            HumanMessage(with_ui(state["user_text"], state.get("ui_context"))),
        ]
        response = await llm.get_chat_llm().bind_tools(await ctx.tools()).ainvoke(messages)
        update = {"messages": [*messages, response], "new_pending": state.get("pending")}
        if not response.tool_calls or state.get("tool_rounds", 0) >= MAX_TOOL_ROUNDS:
            update["reply"] = response.text or FALLBACK_REPLY
        return update

    def after_agent(state: AgentState) -> str:
        return END if "reply" in state else "tools"

    async def tools_node(state: AgentState) -> dict:
        last: AIMessage = state["messages"][-1]
        tools_by_name = {tool.name: tool for tool in await ctx.tools()}
        results, card = [], state.get("card")
        screen, screen_params = state.get("screen"), state.get("screen_params")
        for call in last.tool_calls:
            tool = tools_by_name.get(call["name"])
            if tool is None:
                output = json.dumps({"error": "없는 도구입니다."}, ensure_ascii=False)
            else:
                try:
                    output = tool_text(await tool.ainvoke(call["args"]))
                except Exception:  # 잘못된 인자 등. 오류 내용은 LLM에 넘기지 않는다
                    output = json.dumps({"error": "조회에 실패했습니다."}, ensure_ascii=False)
            if call["name"] == "get_my_accounts":
                try:
                    card = {"type": "account_summary", "accounts": json.loads(output)["accounts"]}
                except (ValueError, KeyError):
                    pass
            try:
                parsed = json.loads(output)
                shown = screen_for(call["name"], call["args"], parsed if isinstance(parsed, dict) else {})
            except (ValueError, KeyError, TypeError):
                shown = None
            if shown:
                screen, screen_params = shown
            results.append(ToolMessage(content=output, tool_call_id=call["id"], name=call["name"]))
        return {"messages": [*state["messages"], *results], "card": card, "screen": screen, "screen_params": screen_params,
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
