"""E2E(Playwright) 테스트용 DB 준비: 빈 SQLite 파일에 테이블을 만들고 시연 데이터(demo_seed.py)를 넣는다.

    DATABASE_URL=sqlite+aiosqlite:///./e2e.db uv run python scripts/e2e_prepare.py

frontend/playwright.config.ts가 백엔드를 띄우기 전에 부른다. 실수로 개발·운영 DB를 지우지 않도록
DATABASE_URL이 SQLite가 아니면 멈춘다. 마이그레이션 대신 모델로 테이블을 만든다 (tests/conftest.py와 같은 방식).
"""

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL.startswith("sqlite+aiosqlite:///"):
    sys.exit(f"e2e_prepare: SQLite DATABASE_URL만 쓸 수 있습니다 (지금: {DATABASE_URL.split('://')[0] or '없음'})")

import avengers_bank.main  # noqa: E402,F401  라우터를 import하면 모든 모델이 Base에 등록된다
from avengers_bank.core.database import Base, engine  # noqa: E402


def load_demo_seed():
    spec = importlib.util.spec_from_file_location("demo_seed", ROOT / "scripts" / "demo_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await load_demo_seed().main()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
