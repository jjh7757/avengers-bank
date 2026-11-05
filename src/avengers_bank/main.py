import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import engine
from avengers_bank.core.exception_handlers import register_exception_handlers
from avengers_bank.core.health import router as health_router
from avengers_bank.core.logging import REQUEST_ID_HEADER, RequestContextMiddleware, configure_logging
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.core.sentry import init_sentry
from avengers_bank.domains.accounts.router import router as account_router
from avengers_bank.domains.cards.router import router as card_router
from avengers_bank.domains.chat.router import router as chat_router
from avengers_bank.domains.demo.router import router as demo_router
from avengers_bank.domains.fds.router import router as fds_router
from avengers_bank.domains.fds.scorer import fds_scorer
from avengers_bank.domains.interbank.router import router as interbank_router
from avengers_bank.domains.interbank.worker import confirm_loop
from avengers_bank.domains.products.router import router as product_router
from avengers_bank.domains.recipients.router import router as recipient_router
from avengers_bank.domains.speech.router import router as voice_router
from avengers_bank.domains.transfers.router import router as transfer_router
from avengers_bank.domains.users.router import router as user_router
from avengers_bank.mcp_servers.registry import mount_mcp_servers, run_mcp_servers

configure_logging()  # JSON 로그 (LOG_FORMAT=text면 사람이 읽는 형식)
init_sentry()  # SENTRY_DSN이 있을 때만


@asynccontextmanager
async def lifespan(app: FastAPI):
    fds_scorer.load()  # LightGBM 모델은 앱 시작 때 한 번만 읽는다
    # 처리 중 타행 이체 확인 (ClearingHub 설정이 있을 때만)
    confirm_task = asyncio.create_task(confirm_loop()) if get_settings().interbank_enabled else None
    try:
        async with run_mcp_servers():  # 에이전트가 쓰는 MCP 서버 (/mcp/*)
            yield
    finally:
        if confirm_task is not None:
            confirm_task.cancel()
            with suppress(asyncio.CancelledError):
                await confirm_task
        await engine.dispose()


app = FastAPI(title="AvengersBank", lifespan=lifespan, responses=error_responses(500))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
    expose_headers=[REQUEST_ID_HEADER],
)
# 마지막에 단 미들웨어가 가장 바깥이다: CORS 응답(preflight 포함)에도 request ID가 붙는다
app.add_middleware(RequestContextMiddleware)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(user_router)
app.include_router(product_router)
app.include_router(account_router)
app.include_router(transfer_router)
app.include_router(card_router)
app.include_router(recipient_router)
app.include_router(fds_router)
app.include_router(chat_router)
app.include_router(voice_router)
app.include_router(demo_router)
app.include_router(interbank_router)
mount_mcp_servers(app)


@app.get("/", response_model=SuccessResponse[dict[str, str]])
async def get_root():
    return SuccessResponse[dict[str, str]](data={"Hello": "AvengersBank"})
