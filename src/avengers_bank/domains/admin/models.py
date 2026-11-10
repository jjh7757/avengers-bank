from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class AdminAction(StrEnum):
    RESERVE_REQUEST_CREATE = "RESERVE_REQUEST_CREATE"  # 허브 예치금 입금·인출 신청
    RESERVE_REQUEST_CANCEL = "RESERVE_REQUEST_CANCEL"  # 결정 전 신청 취소
    RESERVE_SYNC = "RESERVE_SYNC"  # 열린 신청을 허브와 맞춤 (승인이면 장부 반영)


class AuditResult(StrEnum):
    OK = "OK"
    FAILED = "FAILED"


class AdminAuditLog(Base):
    """관리자 행동 기록. 실패한 시도도 남긴다: 본 작업과 따로 커밋해서 예외로 롤백되지 않는다.
    지우거나 고치는 API는 두지 않는다."""

    __tablename__ = "admin_audit_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)  # AdminAction
    target: Mapped[str | None] = mapped_column(String(64))  # 대상 (예: 예치금 신청 id)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # 요청 내용·결과 (kind, amount, memo, status …)
    result: Mapped[str] = mapped_column(String(10), nullable=False)  # AuditResult
    error_code: Mapped[str | None] = mapped_column(String(64))
    client_ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
