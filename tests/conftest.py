import os

# 앱을 import하기 전에 테스트용 설정을 넣는다 (SQLite 파일 DB).
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-test-secret-key-0000"

import pytest
from httpx import ASGITransport, AsyncClient

import avengers_bank.domains.accounts.models  # noqa: F401  모든 테이블을 Base에 등록
import avengers_bank.domains.cards.models  # noqa: F401
import avengers_bank.domains.products.models  # noqa: F401
from avengers_bank.core.database import Base, engine
from avengers_bank.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
