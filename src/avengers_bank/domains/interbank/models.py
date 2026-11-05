from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class InterbankStatus(StrEnum):
    PENDING = "PENDING"  # 출금했고 허브 결과를 기다림. 이 행이 '타행 송금 중간 계정' 역할을 한다
    COMPLETED = "COMPLETED"  # 받는 은행 입금 확인
    FAILED = "FAILED"  # 받는 은행·허브가 거절 → 출금을 되돌림


class InterbankTransfer(Base):
    """우리 고객이 다른 은행으로 보낸 이체. 상태가 PENDING인 동안의 금액 합계가 송금 중인 돈이다."""

    __tablename__ = "interbank_transfers"

    transfer_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # 허브에 보내는 UUID (멱등성 키)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), index=True, nullable=False)
    checking_account_id: Mapped[int] = mapped_column(
        ForeignKey("checking_accounts.checking_account_id"), nullable=False
    )
    to_bank: Mapped[str] = mapped_column(String(3), nullable=False)
    to_account: Mapped[str] = mapped_column(String(50), nullable=False)
    to_holder_name: Mapped[str | None] = mapped_column(String(50))
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memo: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    fail_code: Mapped[str | None] = mapped_column(String(40))
    fail_message: Mapped[str | None] = mapped_column(String(200))
    check_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 허브에 결과를 물어본 횟수
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterbankReceipt(Base):
    """다른 은행에서 우리 고객에게 들어온 입금. transfer_id로 한 번만 입금한다 (SPEC 4.2)."""

    __tablename__ = "interbank_receipts"

    transfer_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    checking_account_id: Mapped[int] = mapped_column(
        ForeignKey("checking_accounts.checking_account_id"), index=True, nullable=False
    )
    from_bank: Mapped[str] = mapped_column(String(3), nullable=False)
    from_bank_name: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    from_account: Mapped[str] = mapped_column(String(50), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memo: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
