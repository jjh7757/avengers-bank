from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.products.schemas import (
    AccountProductResponse,
    AccountProductType,
    CardProductResponse,
    CardProductType,
    ProductTermsResponse,
)
from avengers_bank.domains.products.service import product_service

router = APIRouter(prefix="/products", tags=["products"], responses=error_responses(422))


@router.get("/accounts", response_model=SuccessResponse[list[AccountProductResponse]])
async def get_account_products(
    db: Annotated[AsyncSession, Depends(get_db)], type: AccountProductType | None = None
):
    products = await product_service.get_account_products(db, type)
    return SuccessResponse[list[AccountProductResponse]](data=products)


@router.get(
    "/accounts/{product_id}",
    response_model=SuccessResponse[AccountProductResponse],
    responses=error_responses(404),
)
async def get_account_product(product_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    product = await product_service.get_account_product(db, product_id)
    return SuccessResponse[AccountProductResponse](data=product)


@router.get("/cards", response_model=SuccessResponse[list[CardProductResponse]])
async def get_card_products(
    db: Annotated[AsyncSession, Depends(get_db)], type: CardProductType | None = None
):
    products = await product_service.get_card_products(db, type)
    return SuccessResponse[list[CardProductResponse]](data=products)


@router.get(
    "/cards/{product_id}",
    response_model=SuccessResponse[CardProductResponse],
    responses=error_responses(404),
)
async def get_card_product(product_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    product = await product_service.get_card_product(db, product_id)
    return SuccessResponse[CardProductResponse](data=product)


@router.get(
    "/accounts/{product_id}/terms",
    response_model=SuccessResponse[ProductTermsResponse],
    responses=error_responses(404),
)
async def get_account_product_terms(product_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    """계좌 상품 이용약관. 동의하면 version을 개설 요청의 terms_version에 넣는다"""
    terms = await product_service.get_terms(db, "account", product_id)
    return SuccessResponse[ProductTermsResponse](data=terms)


@router.get(
    "/cards/{product_id}/terms",
    response_model=SuccessResponse[ProductTermsResponse],
    responses=error_responses(404),
)
async def get_card_product_terms(product_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    """카드 상품 이용약관. 동의하면 version을 발급 요청의 terms_version에 넣는다"""
    terms = await product_service.get_terms(db, "card", product_id)
    return SuccessResponse[ProductTermsResponse](data=terms)
