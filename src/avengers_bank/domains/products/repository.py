from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.products.models import AccountProduct, CardProduct


class ProductRepository:
    async def find_account_products(
        self, db: AsyncSession, type: str | None = None
    ) -> list[AccountProduct]:
        stmt = select(AccountProduct).order_by(AccountProduct.product_id)
        if type is not None:
            stmt = stmt.where(AccountProduct.type == type)
        return list(await db.scalars(stmt))

    async def find_account_product_by_id(
        self, db: AsyncSession, product_id: int
    ) -> AccountProduct | None:
        return await db.get(AccountProduct, product_id)

    async def find_card_products(
        self, db: AsyncSession, type: str | None = None
    ) -> list[CardProduct]:
        stmt = select(CardProduct).order_by(CardProduct.product_id)
        if type is not None:
            stmt = stmt.where(CardProduct.type == type)
        return list(await db.scalars(stmt))

    async def find_card_product_by_id(
        self, db: AsyncSession, product_id: int
    ) -> CardProduct | None:
        return await db.get(CardProduct, product_id)


product_repository = ProductRepository()
