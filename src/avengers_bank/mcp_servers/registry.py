"""MCP 서버 등록: FastAPI의 /mcp/{이름}/mcp 에 streamable HTTP로 붙인다.

    /mcp/accounts/mcp   계좌      /mcp/transfers/mcp  이체·수취인    /mcp/products/mcp  상품
    /mcp/cards/mcp      카드      /mcp/security/mcp   FDS 판정 기록
    /mcp/knowledge/mcp  상품 약관·FAQ 검색 (RAG)

외부 MCP 클라이언트(Claude Desktop 등)도 같은 주소에 `Authorization: Bearer <JWT>`로 붙을 수 있다.
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from avengers_bank.mcp_servers import accounts, cards, knowledge, products, security, transfers

SERVERS: dict[str, FastMCP] = {
    "accounts": accounts.server,
    "transfers": transfers.server,
    "products": products.server,
    "cards": cards.server,
    "security": security.server,
    "knowledge": knowledge.server,
}
MCP_PATH = "/mcp"


def server_url(base_url: str, name: str) -> str:
    return f"{base_url}{MCP_PATH}/{name}/mcp"


class _McpMount:
    """마운트된 ASGI 앱을 lifespan마다 새로 만든다.
    FastMCP의 세션 매니저는 run()을 한 번만 할 수 있어서, 앱을 다시 시작하는 테스트에서도 동작하도록."""

    def __init__(self, server: FastMCP) -> None:
        self.server = server
        self.app = None

    async def __call__(self, scope, receive, send) -> None:
        if self.app is None:
            raise RuntimeError("MCP 서버가 시작되지 않았습니다 (FastAPI lifespan 밖)")
        await self.app(scope, receive, send)


_mounts = {name: _McpMount(server) for name, server in SERVERS.items()}


def mount_mcp_servers(app: FastAPI) -> None:
    for name, mount in _mounts.items():
        app.mount(f"{MCP_PATH}/{name}", mount)


@asynccontextmanager
async def run_mcp_servers() -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        for mount in _mounts.values():
            mount.server._session_manager = None  # 새 세션 매니저 (FastMCP는 run()을 한 번만 허용)
            mount.app = mount.server.streamable_http_app()
            await stack.enter_async_context(mount.server.session_manager.run())
        try:
            yield
        finally:
            for mount in _mounts.values():
                mount.app = None
