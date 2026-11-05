from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from avengers_bank.domains.products.schemas import TERMS_VERSION_FIELD

CardType = Literal["credit", "debit"]


class CreditCardCreate(BaseModel):
    product_id: int
    terms_version: str = Field(**TERMS_VERSION_FIELD)
    checking_account_id: int = Field(description="결제 계좌 (본인 입출금 계좌)")
    payment_date: int = Field(ge=1, le=31, description="매월 결제일")


class DebitCardCreate(BaseModel):
    product_id: int
    terms_version: str = Field(**TERMS_VERSION_FIELD)
    checking_account_id: int = Field(description="출금 계좌 (본인 입출금 계좌)")


class CardPaymentCreate(BaseModel):
    place_of_use: str = Field(min_length=1, max_length=100)
    used_amount: int = Field(gt=0)


class CardSummaryResponse(BaseModel):
    """GET /cards — 신용·체크카드를 한 목록으로 보여줄 때 쓰는 공통 모양"""

    card_type: str  # credit / debit
    card_id: int
    card_num: str
    checking_account_id: int
    accumulated_amount: int

    model_config = ConfigDict(from_attributes=True)


class CardDetailResponse(CardSummaryResponse):
    product_id: int
    payment_date: int | None = None  # credit


class CardHistoryResponse(BaseModel):
    history_id: int
    place_of_use: str
    used_amount: int
    time: datetime


class CardPaymentResponse(BaseModel):
    card_type: str
    card_id: int
    place_of_use: str
    used_amount: int
    accumulated_amount: int
    account_balance_after: int | None = None  # 체크카드: 연결 계좌의 결제 후 잔액
    paid_at: datetime
