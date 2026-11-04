from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TransferCreate(BaseModel):
    """POST /transfers — 입출금 → 입출금 이체. 아래 4개 필드는 FDS가 쓴다."""

    from_checking_account_id: int
    to_account_num: str = Field(min_length=1, max_length=20)
    amount: int = Field(gt=0)
    pin: str | None = Field(
        default=None, pattern=r"^\d{6}$", repr=False,
        description="FDS가 ADDITIONAL_AUTH_REQUIRED를 돌려준 뒤 다시 보낼 때 넣는 이체 PIN",
    )
    device_fingerprint: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(
        default=None, max_length=64,
        description="채팅에서 온 이체면 대화 ID. 이 값이 있으면 confirmation_token이 반드시 필요하다",
    )
    confirmation_token: str | None = Field(
        default=None, max_length=2000, repr=False, description="에이전트 확인 카드의 승인 토큰"
    )
    input_mode: Literal["text", "voice"] = "text"


class SavingsPaymentCreate(BaseModel):
    """POST /transfers/savings — 입출금 → 본인 적금 납입. amount를 비우면 월 납입액."""

    from_checking_account_id: int
    savings_account_id: int
    amount: int | None = Field(default=None, gt=0)


class DepositPaymentCreate(BaseModel):
    """POST /transfers/deposit — 입출금 → 본인 예금 입금"""

    from_checking_account_id: int
    deposit_account_id: int
    amount: int = Field(gt=0)


class TransferResponse(BaseModel):
    from_account_num: str
    to_account_num: str
    to_holder_name: str | None = None  # 입출금 → 입출금 이체일 때 받는 사람 이름
    amount: int
    balance_after: int  # 보낸 계좌의 이체 후 잔액
    transferred_at: datetime
    risk_level: str | None = None  # 입출금 → 입출금 이체의 FDS 판정 (LOW / MEDIUM)
