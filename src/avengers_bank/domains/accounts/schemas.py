from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from avengers_bank.domains.products.schemas import TERMS_VERSION_FIELD

AccountType = Literal["checking", "deposit", "savings"]

# 이체 한도 기본값 (PROJECT_PLAN.md 8절)
DEFAULT_PER_TRANSFER_LIMIT = 5_000_000
DEFAULT_DAILY_TRANSFER_LIMIT = 10_000_000
MAX_TRANSFER_LIMIT = 100_000_000


class _TransferLimits(BaseModel):
    @model_validator(mode="after")
    def check_limits(self) -> Self:
        per, daily = self.per_transfer_limit, self.daily_transfer_limit
        if per is not None and daily is not None and per > daily:
            raise ValueError("1회 이체 한도는 1일 이체 한도보다 클 수 없습니다.")
        return self


class CheckingAccountCreate(_TransferLimits):
    product_id: int
    terms_version: str = Field(**TERMS_VERSION_FIELD)
    nickname: str | None = Field(default=None, max_length=50)
    per_transfer_limit: int = Field(default=DEFAULT_PER_TRANSFER_LIMIT, gt=0, le=MAX_TRANSFER_LIMIT)
    daily_transfer_limit: int = Field(
        default=DEFAULT_DAILY_TRANSFER_LIMIT, gt=0, le=MAX_TRANSFER_LIMIT
    )


class DepositAccountCreate(BaseModel):
    product_id: int
    terms_version: str = Field(**TERMS_VERSION_FIELD)
    term_months: int = Field(ge=1, le=60, description="가입 기간(개월). 만기일 = 오늘 + 기간")
    nickname: str | None = Field(default=None, max_length=50)


class SavingsAccountCreate(BaseModel):
    product_id: int
    terms_version: str = Field(**TERMS_VERSION_FIELD)
    term_months: int = Field(ge=1, le=60)
    monthly_payment: int = Field(gt=0, le=MAX_TRANSFER_LIMIT)
    monthly_deposit_date: int = Field(ge=1, le=31, description="매월 납입일")
    nickname: str | None = Field(default=None, max_length=50)


class AccountUpdate(_TransferLimits):
    """보낸 필드만 바꾼다. 이체 한도는 입출금 계좌만 가능."""

    nickname: str | None = Field(default=None, max_length=50)
    per_transfer_limit: int | None = Field(default=None, gt=0, le=MAX_TRANSFER_LIMIT)
    daily_transfer_limit: int | None = Field(default=None, gt=0, le=MAX_TRANSFER_LIMIT)
    # 한도를 높일 때만 필요하다. 로그인이 탈취됐거나 보이스피싱범이 시켜도 한도를 올려 빼 가지 못하게
    pin: str | None = Field(default=None, pattern=r"^\d{6}$", repr=False, description="이체 PIN 6자리 (한도를 높일 때)")


class AccountSummaryResponse(BaseModel):
    """GET /accounts — 3종 계좌를 한 목록으로 보여줄 때 쓰는 공통 모양"""

    account_type: str  # checking / deposit / savings
    account_id: int
    account_num: str
    balance: int
    nickname: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccountDetailResponse(AccountSummaryResponse):
    """계좌 상세. 종류에 없는 필드는 null."""

    product_id: int
    per_transfer_limit: int | None = None  # checking
    daily_transfer_limit: int | None = None  # checking
    maturity_date: date | None = None  # deposit, savings
    monthly_payment: int | None = None  # savings
    monthly_deposit_date: int | None = None  # savings


class AccountHistoryResponse(BaseModel):
    """3종 계좌 거래내역 공통 모양. amount는 입금 +, 출금 -."""

    history_id: int
    date: datetime
    amount: int
    type: str
    from_account: str | None
    sending_account: str | None = None
