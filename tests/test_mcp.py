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
    assert len(SERVERS) == 5
    assert {"get_my_accounts", "open_checking_account", "search_products", "get_my_cards", "get_fds_logs"} <= names
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


async def test_open_account_and_issue_card(client, user):
    mcp = await mcp_for(client, user)
    account = await mcp.call("accounts", "open_checking_account", {"product_id": 1, "nickname": "용돈"})
    assert account["account_num"].startswith("****")

    card = await mcp.call("cards", "issue_debit_card", {"product_id": DEBIT_PRODUCT, "checking_account_id": account["account_id"]})
    assert card["card_type"] == "debit"
    assert len((await mcp.call("cards", "get_my_cards", {}))["cards"]) == 1


async def test_products_and_security(client, user):
    mcp = await mcp_for(client, user)
    products = (await mcp.call("products", "search_products", {"kind": "account", "keyword": "적금"}))["products"]
    assert {p["type"] for p in products} == {"SAVINGS"}
    assert (await mcp.call("security", "get_fds_logs", {}))["logs"] == []
    assert (await mcp.call("security", "get_voice_profile_status", {}))["enrolled"] is False


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
