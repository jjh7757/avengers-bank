from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class AccountProduct(Base):
    __tablename__ = "account_products"

    product_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # CHECKING / DEPOSIT / SAVINGS
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)  # 연 금리(%)


class CardProduct(Base):
    __tablename__ = "card_products"

    product_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # CREDIT / DEBIT
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class TermsAgreement(Base):
    """상품 이용약관 동의 기록. 계좌 개설·카드 발급과 같은 트랜잭션에서 남긴다 (대화든 앱 화면이든)."""

    __tablename__ = "terms_agreements"

    agreement_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    product_kind: Mapped[str] = mapped_column(String(10), nullable=False)  # account / card
    product_id: Mapped[int] = mapped_column(nullable=False)
    terms_version: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(10), nullable=False)  # checking·deposit·savings / credit·debit
    target_id: Mapped[int] = mapped_column(nullable=False)  # 만든 계좌·카드 id
    agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
