from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class CreditCard(Base):
    """신용카드"""

    __tablename__ = "credit_cards"

    credit_card_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("card_products.product_id"), nullable=False
    )
    checking_account_id: Mapped[int] = mapped_column(  # 결제 계좌
        ForeignKey("checking_accounts.checking_account_id"), nullable=False
    )
    card_num: Mapped[str] = mapped_column(String(19), unique=True, nullable=False)
    accumulated_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    payment_date: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 매월 결제일(1~31)


class DebitCard(Base):
    """체크카드"""

    __tablename__ = "debit_cards"

    debit_card_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("card_products.product_id"), nullable=False
    )
    checking_account_id: Mapped[int] = mapped_column(  # 출금 계좌
        ForeignKey("checking_accounts.checking_account_id"), nullable=False
    )
    card_num: Mapped[str] = mapped_column(String(19), unique=True, nullable=False)
    accumulated_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class CreditCardHistory(Base):
    """신용카드 사용내역"""

    __tablename__ = "credit_card_histories"

    credit_card_history_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    credit_card_id: Mapped[int] = mapped_column(
        ForeignKey("credit_cards.credit_card_id"), nullable=False
    )
    place_of_use: Mapped[str] = mapped_column(String(100), nullable=False)
    used_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DebitCardHistory(Base):
    """체크카드 사용내역"""

    __tablename__ = "debit_card_histories"

    debit_card_history_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    debit_card_id: Mapped[int] = mapped_column(
        ForeignKey("debit_cards.debit_card_id"), nullable=False
    )
    place_of_use: Mapped[str] = mapped_column(String(100), nullable=False)
    used_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
