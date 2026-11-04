"""상품 시드 데이터를 .env의 DATABASE_URL DB에 넣는다.

사용법: uv run python scripts/seed_products.py  (alembic upgrade head 이후)
"""

import asyncio
import selectors
import sys

from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.domains.products.seed import seed_products


async def main() -> None:
    try:
        async with SessionLocal() as db, db.begin():
            inserted = await seed_products(db)
        print(f"상품 {inserted}건을 추가했습니다.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg async는 Windows 기본 Proactor 루프에서 동작하지 않는다 (alembic/env.py와 동일).
        asyncio.run(main(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(main())
