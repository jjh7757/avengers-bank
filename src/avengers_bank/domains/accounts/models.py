from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class HistoryType(StrEnum):
    """거래내역 type 컬럼 값 (PROJECT_PLAN.md 8절)"""

    DEPOSIT = "DEPOSIT"  # 예금·적금 계좌에 돈이 들어옴
    WITHDRAW = "WITHDRAW"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    CARD_PAYMENT = "CARD_PAYMENT"  # 체크카드 결제로 입출금 계좌에서 출금
    SAVINGS_PAYMENT = "SAVINGS_PAYMENT"  # 입출금 → 적금 납입 (입출금 쪽 기록)
    DEPOSIT_PAYMENT = "DEPOSIT_PAYMENT"  # 입출금 → 예금 입금 (입출금 쪽 기록)
    INTEREST = "INTEREST"


class CheckingAccount(Base):
    """입출금 계좌"""

    __tablename__ = "checking_accounts"

    checking_account_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("account_products.product_id"), nullable=False
    )
    account_num: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    per_transfer_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    daily_transfer_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DepositAccount(Base):
    """예금 계좌"""

    __tablename__ = "deposit_accounts"

    deposit_account_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("account_products.product_id"), nullable=False
    )
    account_num: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SavingsAccount(Base):
    """적금 계좌"""

    __tablename__ = "savings_accounts"

    savings_account_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("account_products.product_id"), nullable=False
    )
    account_num: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    monthly_payment: Mapped[int] = mapped_column(BigInteger, nullable=False)
    monthly_deposit_date: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 매월 납입일(1~31)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CheckingAccountHistory(Base):
    """입출금 계좌 거래내역 (ERD: Chenking_Account_History)"""

    __tablename__ = "checking_account_histories"

    checking_account_history_id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )
    checking_account_id: Mapped[int] = mapped_column(
        ForeignKey("checking_accounts.checking_account_id"), nullable=False
    )
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    change_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 입금 +, 출금 -
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # HistoryType
    from_account: Mapped[str | None] = mapped_column(String(20))  # 돈이 나간 계좌번호
    sending_account: Mapped[str | None] = mapped_column(String(20))  # 돈이 들어간 계좌번호


class DepositAccountHistory(Base):
    """예금 계좌 거래내역"""

    __tablename__ = "deposit_account_histories"

    deposit_account_history_id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )
    deposit_account_id: Mapped[int] = mapped_column(
        ForeignKey("deposit_accounts.deposit_account_id"), nullable=False
    )
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deposit_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_account: Mapped[str | None] = mapped_column(String(20))


class SavingsAccountHistory(Base):
    """적금 계좌 거래내역"""

    __tablename__ = "savings_account_histories"

    savings_account_history_id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )
    savings_account_id: Mapped[int] = mapped_column(
        ForeignKey("savings_accounts.savings_account_id"), nullable=False
    )
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deposit_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_account: Mapped[str | None] = mapped_column(String(20))
