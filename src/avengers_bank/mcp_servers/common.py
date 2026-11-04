"""MCP 서버 공통: 사용자 인증, DB 세션, 오류를 도구 결과로 바꾸기.

도구는 HTTP 헤더 `Authorization: Bearer <JWT>`로 누구의 요청인지 안다 (REST API와 같은 JWT).
service가 던진 ApiException은 {"error": code, "message": ...}로 돌려준다. 에이전트(LLM)가 그 메시지를 보고 사용자에게 설명한다.
"""

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.exceptions import ApiException, UnauthorizedException
from avengers_bank.domains.users.schemas import UserResponse
from avengers_bank.domains.users.service import user_service

# 로컬 개발·같은 프로세스 호출용. 배포할 때는 실제 호스트를 더한다
ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]


def new_server(name: str, instructions: str) -> FastMCP:
    return FastMCP(
        name,
        instructions=instructions,
        stateless_http=True,  # 요청마다 독립. 대화 상태는 백엔드(chat_sessions)가 가진다
        json_response=True,
        log_level="WARNING",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=ALLOWED_HOSTS, allowed_origins=[]
        ),
    )


async def current_user(ctx: Context, db: AsyncSession) -> UserResponse:
    request = ctx.request_context.request
    header = request.headers.get("authorization", "") if request is not None else ""
    if not header.lower().startswith("bearer "):
        raise UnauthorizedException(message="로그인이 필요합니다.", code="AUTHENTICATION_REQUIRED")
    user = await user_service.get_current_user(db, header[7:])
    return UserResponse.model_validate(user)


Handler = Callable[..., Awaitable[Any]]


def bank_tool(server: FastMCP, **tool_kwargs):
    """도구 함수는 (db, user, 도구 인자들...)을 받는다. 인증·DB 세션·오류 변환은 여기서 한다.

    MCP에 보이는 시그니처는 도구 인자 + ctx만 남긴다 (db, user는 숨김).
    """

    def decorator(fn: Handler) -> Handler:
        params = [p for name, p in inspect.signature(fn).parameters.items() if name not in ("db", "user")]
        params.append(inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context))

        @functools.wraps(fn)
        async def wrapper(*args, ctx: Context, **kwargs):
            try:
                async with SessionLocal() as db:
                    user = await current_user(ctx, db)
                    await db.rollback()  # 인증 조회로 열린 트랜잭션을 닫아야 service가 자기 트랜잭션을 연다
                    return await fn(db, user, *args, **kwargs)
            except ApiException as e:
                return {"error": e.code, "message": e.message}

        wrapper.__signature__ = inspect.Signature(params, return_annotation=inspect.signature(fn).return_annotation)
        wrapper.__annotations__ = {**{p.name: p.annotation for p in params}, "return": dict}
        return server.tool(**tool_kwargs)(wrapper)

    return decorator


def mask(number: str) -> str:
    """계좌·카드번호는 뒤 4자리만: 110-123-456789 → ****6789 (LLM이 번호 전체를 말하지 않게)"""
    return "****" + number.replace("-", "")[-4:]
