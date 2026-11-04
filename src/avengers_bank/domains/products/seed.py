"""data/seed/products.json을 DB에 넣는다. 같은 이름의 상품이 있으면 건너뛴다.

scripts/seed_products.py와 테스트가 같은 함수를 쓴다.
"""

import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.products.models import AccountProduct, CardProduct

SEED_PATH = Path(__file__).resolve().parents[4] / "data" / "seed" / "products.json"


async def seed_products(db: AsyncSession, path: Path = SEED_PATH) -> int:
    seed = json.loads(path.read_text(encoding="utf-8"))
    inserted = 0

    existing = set(await db.scalars(select(AccountProduct.name)))
    for item in seed["account_products"]:
        if item["name"] not in existing:
            db.add(AccountProduct(**{**item, "interest_rate": Decimal(item["interest_rate"])}))
            inserted += 1

    existing = set(await db.scalars(select(CardProduct.name)))
    for item in seed["card_products"]:
        if item["name"] not in existing:
            db.add(CardProduct(**item))
            inserted += 1

    await db.flush()
    return inserted
