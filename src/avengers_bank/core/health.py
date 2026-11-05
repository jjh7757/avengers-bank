"""헬스체크: GET /health (운영에서는 /api/health와 /health 둘 다).

로드밸런서·업타임 모니터·배포 스크립트가 부른다. 인증이 필요 없고, DB에 `SELECT 1`을 보내 연결까지 확인한다.
- 200 {"status": "ok", "checks": {"database": "ok"}}
- 503 {"status": "error", "checks": {"database": "error"}}  DB에 닿지 않거나 시간 초과(3초)

모니터링 도구가 상태 코드만 보면 되도록 다른 API의 SuccessResponse 형식 대신 평평한 JSON을 쓴다.
오류 내용(접속 주소 등)은 응답에 넣지 않고 서버 로그에만 남긴다.
"""

import asyncio
import logging
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from avengers_bank.core.database import engine

DB_TIMEOUT_SECONDS = 3

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


async def check_database() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


@router.get(
    "/health",
    summary="헬스체크 (DB 연결 포함)",
    responses={503: {"description": "DB 연결 실패"}},
)
async def health() -> JSONResponse:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(check_database(), timeout=DB_TIMEOUT_SECONDS)
        database = "ok"
    except Exception:
        logger.error("헬스체크: DB에 연결하지 못했습니다.", exc_info=True)
        database = "error"
    ok = database == "ok"
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ok" if ok else "error",
            "checks": {"database": database},
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
        headers={"Cache-Control": "no-store"},
    )
