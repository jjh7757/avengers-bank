"""에이전트의 MCP 클라이언트. 같은 FastAPI 앱 안의 MCP 서버를 ASGI로 직접 부른다 (네트워크를 거치지 않음).

- LLM 도구(llm_tools): 모든 MCP 도구 중 LLM_EXCLUDED를 뺀 것
- 이체 노드(call): 정해진 순서로 MCP 도구를 직접 부른다 (수취인 찾기 → 확인 카드)
"""

import json
from typing import Any

import httpx
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from avengers_bank.core.security import create_access_token
from avengers_bank.mcp_servers.registry import SERVERS, server_url

BASE_URL = "http://127.0.0.1:8000"  # Host 검사용 이름. 실제로는 ASGITransport로 같은 프로세스 안에서 호출한다

# MCP 서버에는 있지만 LLM에게는 주지 않는 도구
LLM_EXCLUDED = {
    "prepare_transfer",  # 이체 카드는 금액 재검증을 거친 이체 노드만 만든다
    "execute_transfer",  # 돈은 사용자가 확인 카드에서 승인할 때만 움직인다 (앱이 POST /transfers)
    "register_recipient",  # 수취인 등록 = FDS "처음 보내는 계좌" 검사를 건너뜀. 붙여넣은 글에 속아 등록하지 않게
    "rename_recipient",  # "엄마"를 다른 계좌로 바꿔치기하지 않게
    "delete_recipient",
}


class BankMcpClient:
    def __init__(self, user_id: int) -> None:
        from avengers_bank.main import app  # 순환 import 방지 (main → chat → agents)

        def http_client(headers=None, timeout=None, auth=None) -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL, headers=headers, timeout=timeout, auth=auth
            )

        token = create_access_token(user_id)  # 이 대화 처리 동안만 쓰는 사용자 토큰
        self._client = MultiServerMCPClient({
            name: {
                "transport": "streamable_http",
                "url": server_url(BASE_URL, name),
                "headers": {"Authorization": f"Bearer {token}"},
                "httpx_client_factory": http_client,
            }
            for name in SERVERS
        })

    async def llm_tools(self) -> list[BaseTool]:
        return [tool for tool in await self._client.get_tools() if tool.name not in LLM_EXCLUDED]

    async def call(self, server: str, tool: str, args: dict[str, Any]) -> dict:
        """도구를 직접 불러 JSON 결과를 돌려준다. 실패하면 {"error": ..., "message": ...}"""
        async with self._client.session(server) as session:
            result = await session.call_tool(tool, args)
        text = "".join(block.text for block in result.content if getattr(block, "type", "") == "text")
        if result.isError:
            return {"error": "TOOL_ERROR", "message": text or "도구 호출에 실패했습니다."}
        return json.loads(text) if text else {}
