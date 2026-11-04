from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from avengers_bank.core.config import get_settings

settings = get_settings()
# 운영 서버의 공용 PostgreSQL(max_connections 50)을 여러 앱이 나눠 쓰므로 연결 수를 작게 묶는다
pool = {"pool_size": 5, "max_overflow": 5} if settings.database_url.startswith("postgresql") else {}
engine = create_async_engine(settings.database_url, echo=settings.db_echo, **pool)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as db:
        yield db
