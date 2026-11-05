"""운영 진입점: React 빌드(정적 파일)와 API를 한 컨테이너·한 출처로 서빙한다.

    uvicorn avengers_bank.prod:app --host 0.0.0.0 --port 8000

- API는 /api 아래에 둔다. 개발 서버(Vite)가 /api를 FastAPI로 넘기는 것과 같은 경로라 프론트 코드를 바꿀 필요가 없다.
- 그 밖의 경로는 SPA다. 파일이 있으면 그 파일, 없으면 index.html (새로고침해도 /accounts 같은 화면이 열리게).
- 개발할 때는 지금처럼 avengers_bank.main:app(API만)을 쓴다.
- 헬스체크는 /api/health와 /health 둘 다 된다 (SPA 경로보다 먼저 등록). 요청 ID·접근 로그는 바깥 앱에서 한 번만 남긴다.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from avengers_bank.core.health import router as health_router
from avengers_bank.core.logging import RequestContextMiddleware
from avengers_bank.main import app as api

FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend" / "dist")).resolve()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 마운트한 앱의 lifespan은 저절로 돌지 않는다 (FDS 모델 로드, MCP 서버 시작)
    async with api.router.lifespan_context(api):
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(RequestContextMiddleware)  # 정적 파일 요청도 로그·request ID를 남긴다
app.include_router(health_router)
app.mount("/api", api)
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets", check_dir=False), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str) -> FileResponse:
    file = (FRONTEND_DIR / path).resolve()
    if path and file.is_file() and FRONTEND_DIR in file.parents:
        return FileResponse(file)
    return FileResponse(FRONTEND_DIR / "index.html")
