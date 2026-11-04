from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class ChatSession(Base):
    """대화 묶음. session_id는 POST /transfers의 session_id로도 쓰여 FDS가 세션 단위로 판단한다."""

    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # UUID 문자열
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    # 대화 사이에 이어지는 상태: {"pending_transfer": {...}, "confirmation_jti": "..."}
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    msg_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.session_id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(20))  # 사용자 메시지의 분류 결과
    input_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="text")  # text / voice
    card: Mapped[dict | None] = mapped_column(JSON)  # 확인 카드·계좌 요약 카드
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
