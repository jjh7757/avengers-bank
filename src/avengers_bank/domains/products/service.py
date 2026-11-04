from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import BadRequestException, NotFoundException
from avengers_bank.domains.products.models import AccountProduct, CardProduct
from avengers_bank.domains.products.repository import product_repository
from avengers_bank.domains.products.schemas import AccountProductType, CardProductType


class ProductService:
    async def get_account_products(
        self, db: AsyncSession, type: AccountProductType | None
    ) -> list[AccountProduct]:
        async with db.begin():
            return await product_repository.find_account_products(db, type)

    async def get_account_product(self, db: AsyncSession, product_id: int) -> AccountProduct:
        async with db.begin():
            return await self._find_account_product(db, product_id)

    async def get_card_products(
        self, db: AsyncSession, type: CardProductType | None
    ) -> list[CardProduct]:
        async with db.begin():
            return await product_repository.find_card_products(db, type)

    async def get_card_product(self, db: AsyncSession, product_id: int) -> CardProduct:
        async with db.begin():
            return await self._find_card_product(db, product_id)

    # 아래 두 메서드는 accounts·cards 도메인이 열어 둔 트랜잭션 안에서 호출한다.
    async def validate_account_product(
        self, db: AsyncSession, product_id: int, expected_type: AccountProductType
    ) -> AccountProduct:
        product = await self._find_account_product(db, product_id)
        if product.type != expected_type:
            raise BadRequestException(
                code="PRODUCT_TYPE_MISMATCH",
                message=f"{expected_type} 계좌를 개설할 수 없는 상품입니다.",
            )
        return product

    async def validate_card_product(
        self, db: AsyncSession, product_id: int, expected_type: CardProductType
    ) -> CardProduct:
        product = await self._find_card_product(db, product_id)
        if product.type != expected_type:
            raise BadRequestException(
                code="PRODUCT_TYPE_MISMATCH",
                message=f"{expected_type} 카드를 발급할 수 없는 상품입니다.",
            )
        return product

    async def _find_account_product(self, db: AsyncSession, product_id: int) -> AccountProduct:
        product = await product_repository.find_account_product_by_id(db, product_id)
        if product is None:
            raise NotFoundException(code="PRODUCT_NOT_FOUND", message="상품을 찾을 수 없습니다.")
        return product

    async def _find_card_product(self, db: AsyncSession, product_id: int) -> CardProduct:
        product = await product_repository.find_card_product_by_id(db, product_id)
        if product is None:
            raise NotFoundException(code="PRODUCT_NOT_FOUND", message="상품을 찾을 수 없습니다.")
        return product


product_service = ProductService()
