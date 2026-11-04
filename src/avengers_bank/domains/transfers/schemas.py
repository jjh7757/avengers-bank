from pydantic import BaseModel, Field


class TransferCreate(BaseModel):
    """POST /transfers — 입출금 → 입출금 이체"""

    from_checking_account_id: int
    to_account_num: str = Field(min_length=1, max_length=20)
    amount: int = Field(gt=0)


# TODO: SavingsPaymentCreate (적금 납입), DepositPaymentCreate (예금 입금)
# TODO: TransferResponse — 이체 후 잔액 등
