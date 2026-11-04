from datetime import datetime

from pydantic import BaseModel, Field


class TransferCreate(BaseModel):
    """POST /transfers — 입출금 → 입출금 이체"""

    from_checking_account_id: int
    to_account_num: str = Field(min_length=1, max_length=20)
    amount: int = Field(gt=0)


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
