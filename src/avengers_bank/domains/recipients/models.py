from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class Recipient(Base):
    """자주 보내는 수취인 ("엄마", "집주인"). 에이전트의 별칭 → 계좌번호 변환과 FDS 신규 수취인 판정에 쓴다."""

    __tablename__ = "recipients"
    __table_args__ = (
        UniqueConstraint("user_id", "account_num", name="uq_recipients_user_account_num"),
        UniqueConstraint("user_id", "nickname", name="uq_recipients_user_nickname"),
    )

    recipient_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    account_num: Mapped[str] = mapped_column(String(20), nullable=False)  # 입출금 계좌번호
    holder_name: Mapped[str] = mapped_column(String(50), nullable=False)  # 예금주 (등록 시점 이름)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
