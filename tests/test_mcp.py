"""MCP 서버 테스트: 에이전트와 같은 방법(MultiServerMCPClient + ASGI)으로 도구를 부른다."""

import httpx
import pytest
from langchain_mcp_adapters.client import MultiServerMCPClient

from avengers_bank.agents.mcp_client import LLM_EXCLUDED, BankMcpClient
from avengers_bank.main import app
from avengers_bank.mcp_servers.registry import SERVERS
from tests.conftest import DEBIT_PRODUCT, new_chat_session, open_checking

pytestmark = pytest.mark.anyio


async def user_id(client, headers) -> int:
    return (await client.get("/users/me", headers=headers)).json()["data"]["user_id"]


async def mcp_for(client, headers) -> BankMcpClient:
    return BankMcpClient(await user_id(client, headers))


async def test_servers_and_llm_tools(client, user):
    mcp = await mcp_for(client, user)
    names = {tool.name for tool in await mcp.llm_tools()}
    assert len(SERVERS) == 6
    assert {"get_my_accounts", "search_products", "prepare_signup", "get_my_cards", "get_fds_logs", "search_terms"} <= names
    # 개설·발급은 LLM에게 주지 않는다 (가입 화면에서 사용자가 약관에 동의하고 직접)
    assert not {"open_checking_account", "open_savings_account", "issue_debit_card", "issue_credit_card"} & names
    assert not LLM_EXCLUDED & names


async def test_requires_jwt(client):
    def http_client(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                                 headers=headers, timeout=timeout)

    anonymous = MultiServerMCPClient({"accounts": {
        "transport": "streamable_http", "url": "http://127.0.0.1:8000/mcp/accounts/mcp", "httpx_client_factory": http_client,
    }})
    async with anonymous.session("accounts") as session:
        result = await session.call_tool("get_my_accounts", {})
    assert "AUTHENTICATION_REQUIRED" in result.content[0].text


async def test_rejects_unknown_host(client):
    """DNS rebinding 방지: 허용하지 않은 Host로 온 요청은 거절"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://evil.example") as raw:
        response = await raw.post("/mcp/accounts/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                  headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code in (400, 403, 421)


async def test_accounts_are_masked_and_scoped(client, user, other_user):
    mine = await open_checking(client, user, balance=10_000, nickname="생활비")
    others = await open_checking(client, other_user)
    mcp = await mcp_for(client, user)

    [account] = (await mcp.call("accounts", "get_my_accounts", {}))["accounts"]
    assert account["account_num"] == "****" + mine["account_num"][-4:]
    assert account["balance"] == 10_000

    result = await mcp.call("accounts", "get_account", {"account_type": "checking", "account_id": others["account_id"]})
    assert result["error"] == "ACCOUNT_FORBIDDEN"


async def test_limits_can_only_go_down(client, user):
    mine = await open_checking(client, user)
    mcp = await mcp_for(client, user)

    result = await mcp.call("accounts", "lower_transfer_limits", {"checking_account_id": mine["account_id"], "daily_transfer_limit": 50_000_000})
    assert result["error"] == "LIMIT_RAISE_NOT_ALLOWED"

    result = await mcp.call("accounts", "lower_transfer_limits", {"checking_account_id": mine["account_id"], "per_transfer_limit": 1_000_000})
    assert result["per_transfer_limit"] == 1_000_000


async def test_open_account_and_issue_card_need_terms(client, user):
    """외부 클라이언트: prepare_signup으로 약관을 받아 사용자 동의 후 그 버전으로 개설·발급"""
    mcp = await mcp_for(client, user)
    no_terms = await mcp.call("accounts", "open_checking_account", {"product_id": 1, "terms_version": "old"})
    assert no_terms["error"] == "TERMS_NOT_AGREED"

    signup = await mcp.call("products", "prepare_signup", {"kind": "account", "product_id": 1})
    account = await mcp.call("accounts", "open_checking_account",
                             {"product_id": 1, "nickname": "용돈", "terms_version": signup["terms"]["version"]})
    assert account["account_num"].startswith("****")

    version = (await mcp.call("products", "prepare_signup", {"kind": "card", "product_id": DEBIT_PRODUCT}))["terms"]["version"]
    card = await mcp.call("cards", "issue_debit_card",
                          {"product_id": DEBIT_PRODUCT, "checking_account_id": account["account_id"], "terms_version": version})
    assert card["card_type"] == "debit"
    assert len((await mcp.call("cards", "get_my_cards", {}))["cards"]) == 1


async def test_products_and_security(client, user):
    mcp = await mcp_for(client, user)
    products = (await mcp.call("products", "search_products", {"kind": "account", "keyword": "적금"}))["products"]
    assert {p["type"] for p in products} == {"SAVINGS"}
    assert (await mcp.call("security", "get_fds_logs", {}))["logs"] == []


async def test_prepare_transfer_card_can_be_approved(client, user, other_user):
    mine = await open_checking(client, user, balance=100_000)
    mom = await open_checking(client, other_user)
    await client.post("/recipients", headers=user, json={"account_num": mom["account_num"], "nickname": "엄마"})
    session_id = await new_chat_session(client, user)
    mcp = await mcp_for(client, user)

    card = await mcp.call("transfers", "prepare_transfer", {
        "session_id": session_id, "from_checking_account_id": mine["account_id"], "amount": 30_000, "recipient_nickname": "엄마",
    })
    assert (card["to_account_num"], card["holder_name"]) == (mom["account_num"], "브루스 배너")

    response = await client.post("/transfers", headers=user, json={
        "from_checking_account_id": mine["account_id"], "to_account_num": card["to_account_num"], "amount": 30_000,
        "session_id": session_id, "confirmation_token": card["confirmation_token"],
    })
    assert response.status_code == 200, response.text


async def test_prepare_transfer_rejects_others_session(client, user, other_user):
    mine = await open_checking(client, user, balance=100_000)
    target = await open_checking(client, other_user)
    others_session = await new_chat_session(client, other_user)
    mcp = await mcp_for(client, user)

    result = await mcp.call("transfers", "prepare_transfer", {
        "session_id": others_session, "from_checking_account_id": mine["account_id"], "amount": 1_000,
        "to_account_num": target["account_num"],
    })
    assert result["error"] == "CHAT_SESSION_NOT_FOUND"


async def set_pin(client, headers, pin="123456"):
    response = await client.put("/users/me/pin", headers=headers, json={"password": "password1234", "pin": pin})
    assert response.status_code == 200


async def test_execute_transfer_needs_pin_and_runs_once(client, user, other_user):
    """외부 MCP 클라이언트: 대화 없이 카드를 만들고, 사용자가 입력한 PIN으로만 실행한다"""
    mine = await open_checking(client, user, balance=100_000)
    target = await open_checking(client, other_user)
    mcp = await mcp_for(client, user)
    assert "execute_transfer" in LLM_EXCLUDED  # 우리 에이전트 LLM에는 주지 않는다

    card = await mcp.call("transfers", "prepare_transfer", {
        "from_checking_account_id": mine["account_id"], "amount": 30_000, "to_account_num": target["account_num"],
    })
    args = {k: card[k] for k in ("session_id", "confirmation_token", "from_checking_account_id", "to_account_num", "amount")}
    assert len(card["session_id"]) == 32  # 대화가 없으면 새로 만든다

    assert (await mcp.call("transfers", "execute_transfer", args))["error"] == "PIN_REQUIRED"  # 토큰만으로는 실행하지 않는다
    assert (await mcp.call("transfers", "execute_transfer", {**args, "pin": "123456"}))["error"] == "PIN_NOT_SET"
    await set_pin(client, user)
    assert (await mcp.call("transfers", "execute_transfer", {**args, "pin": "000000"}))["error"] == "INVALID_PIN"
    assert (await mcp.call("transfers", "execute_transfer", {**args, "amount": 90_000, "pin": "123456"}))["error"] == "CONFIRMATION_MISMATCH"

    result = await mcp.call("transfers", "execute_transfer", {**args, "pin": "123456"})
    assert result["balance_after"] == 70_000
    assert result["to_account_num"] == "****" + target["account_num"].replace("-", "")[-4:]
    assert result["to_holder_name"] == "브루스 배너"

    assert (await mcp.call("transfers", "execute_transfer", {**args, "pin": "123456"}))["error"] == "CONFIRMATION_USED"
    logs = (await client.get("/fds/logs", headers=user)).json()["data"]
    assert logs[0]["decision"] == "PASS"  # POST /transfers와 같은 FDS 기록이 남는다


async def test_execute_transfer_blocked_by_fds_returns_reasons(client, user, other_user, ml_score):
    mine = await open_checking(client, user, balance=100_000)
    target = await open_checking(client, other_user)
    await set_pin(client, user)
    mcp = await mcp_for(client, user)
    card = await mcp.call("transfers", "prepare_transfer", {
        "from_checking_account_id": mine["account_id"], "amount": 30_000, "to_account_num": target["account_num"],
    })

    ml_score.value = 0.99
    result = await mcp.call("transfers", "execute_transfer", {
        **{k: card[k] for k in ("session_id", "confirmation_token", "from_checking_account_id", "to_account_num", "amount")},
        "pin": "123456",
    })
    assert result["error"] == "FDS_BLOCKED"
    assert result["extra"]["risk_level"] == "HIGH"
    assert "송금을 요구하지 않습니다" in result["extra"]["warning"]
    balance = (await client.get(f"/accounts/checking/{mine['account_id']}", headers=user)).json()["data"]["balance"]
    assert balance == 100_000


async def test_prepare_signup_brings_terms_without_opening(client, user, other_user):
    mine = await open_checking(client, user)
    others = await open_checking(client, other_user)
    mcp = await mcp_for(client, user)

    result = await mcp.call("products", "prepare_signup", {
        "kind": "card", "product_id": DEBIT_PRODUCT, "checking_account_id": mine["account_id"], "term_months": 12})
    assert result["product"]["name"] == "어벤져스 데일리 체크카드"
    assert result["terms"]["version"] and result["terms"]["sections"]
    assert result["prefill"] == {"checking_account_id": mine["account_id"]}  # 카드에 맞지 않는 값은 뺀다
    assert (await mcp.call("cards", "get_my_cards", {}))["cards"] == []  # 발급하지 않는다

    result = await mcp.call("products", "prepare_signup", {
        "kind": "card", "product_id": DEBIT_PRODUCT, "checking_account_id": others["account_id"]})
    assert result["error"] == "ACCOUNT_FORBIDDEN"
