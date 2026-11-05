from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import BadRequestException, NotFoundException
from avengers_bank.domains.products.models import AccountProduct, CardProduct, TermsAgreement
from avengers_bank.domains.products.repository import product_repository
from avengers_bank.domains.products.schemas import (
    AccountProductType,
    CardProductType,
    ProductKind,
    ProductTermsResponse,
    TermsSectionResponse,
)
from avengers_bank.knowledge.terms import find_terms


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

    async def get_terms(self, db: AsyncSession, kind: ProductKind, product_id: int) -> ProductTermsResponse:
        """상품 이용약관 (가입 화면이 보여 주고 동의받는다)"""
        async with db.begin():
            product = await (self._find_account_product if kind == "account" else self._find_card_product)(db, product_id)
            terms = self._terms_of(product)
            return ProductTermsResponse(
                product_kind=kind, product_id=product.product_id, product_type=product.type, product_name=product.name,
                title=terms.title, version=terms.version,
                sections=[TermsSectionResponse(title=s.title, text=s.text) for s in terms.sections],
            )

    # 아래 메서드들은 accounts·cards 도메인이 열어 둔 트랜잭션 안에서 호출한다.
    async def validate_account_product(
        self, db: AsyncSession, product_id: int, expected_type: AccountProductType, terms_version: str
    ) -> AccountProduct:
        product = await self._find_account_product(db, product_id)
        if product.type != expected_type:
            raise BadRequestException(
                code="PRODUCT_TYPE_MISMATCH",
                message=f"{expected_type} 계좌를 개설할 수 없는 상품입니다.",
            )
        self._check_terms(product, terms_version)
        return product

    async def validate_card_product(
        self, db: AsyncSession, product_id: int, expected_type: CardProductType, terms_version: str
    ) -> CardProduct:
        product = await self._find_card_product(db, product_id)
        if product.type != expected_type:
            raise BadRequestException(
                code="PRODUCT_TYPE_MISMATCH",
                message=f"{expected_type} 카드를 발급할 수 없는 상품입니다.",
            )
        self._check_terms(product, terms_version)
        return product

    async def record_agreement(
        self, db: AsyncSession, *, user_id: int, kind: ProductKind, product_id: int, terms_version: str,
        target_type: str, target_id: int,
    ) -> None:
        db.add(TermsAgreement(
            user_id=user_id, product_kind=kind, product_id=product_id, terms_version=terms_version,
            target_type=target_type, target_id=target_id,
        ))
        await db.flush()

    def _terms_of(self, product: AccountProduct | CardProduct):
        terms = find_terms(product.name)
        if terms is None:
            raise NotFoundException(code="TERMS_NOT_FOUND", message="이 상품의 이용약관을 찾을 수 없습니다.")
        return terms

    def _check_terms(self, product: AccountProduct | CardProduct, terms_version: str) -> None:
        """지금 약관 버전에 동의했는지. 약관이 바뀐 뒤의 예전 동의는 받지 않는다 (화면이 새 약관을 다시 보여 준다)"""
        if self._terms_of(product).version != terms_version:
            raise BadRequestException(
                code="TERMS_NOT_AGREED",
                message="이용약관이 바뀌었거나 동의하지 않았습니다. 약관을 다시 확인하고 동의해 주세요.",
            )

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
