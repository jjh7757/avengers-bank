from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

AccountProductType = Literal["CHECKING", "DEPOSIT", "SAVINGS"]
CardProductType = Literal["CREDIT", "DEBIT"]


class AccountProductResponse(BaseModel):
    product_id: int
    type: str
    name: str
    description: str
    interest_rate: Decimal

    model_config = ConfigDict(from_attributes=True)


class CardProductResponse(BaseModel):
    product_id: int
    type: str
    name: str
    description: str

    model_config = ConfigDict(from_attributes=True)


ProductKind = Literal["account", "card"]
TERMS_VERSION_FIELD = {"min_length": 1, "max_length": 40, "description": "동의한 이용약관 버전 (GET /products/{accounts|cards}/{id}/terms의 version)"}


class TermsSectionResponse(BaseModel):
    title: str
    text: str


class ProductTermsResponse(BaseModel):
    """상품 이용약관. 가입 화면이 보여 주고, 동의하면 version을 개설·발급 요청의 terms_version에 넣는다"""

    product_kind: ProductKind
    product_id: int
    product_type: str
    product_name: str
    title: str
    version: str
    sections: list[TermsSectionResponse]
