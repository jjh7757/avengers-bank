from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class FdsDecision(StrEnum):
    PASS = "PASS"  # LOW
    PASS_WITH_AUTH = "PASS_WITH_AUTH"  # MEDIUM + PIN 확인
    AUTH_REQUIRED = "AUTH_REQUIRED"  # MEDIUM, PIN 없음
    AUTH_FAILED = "AUTH_FAILED"  # MEDIUM, PIN 틀림
    BLOCKED = "BLOCKED"  # HIGH


class FdsLog(Base):
    """FDS 판정 기록. 통과·차단 모두 남긴다."""

    __tablename__ = "fds_logs"

    fds_log_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    tx_type: Mapped[str] = mapped_column(String(20), nullable=False)  # TRANSFER
    from_account: Mapped[str] = mapped_column(String(20), nullable=False)
    to_account: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_hits: Mapped[list] = mapped_column(JSON, nullable=False)  # [{"code", "name", "level"}]
    ml_score: Mapped[float | None] = mapped_column(Float)  # 모델이 없으면 null
    top_factors: Mapped[list] = mapped_column(JSON, nullable=False)  # [{"feature", "label", "contribution"}]
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)  # LOW / MEDIUM / HIGH
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # FdsDecision
    input_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserDevice(Base):
    """이체에 성공한 기기. 여기 없는 기기로 이체하면 NEW_DEVICE 규칙에 걸린다.

    로그인만으로는 등록하지 않는다. 탈취한 계정으로 로그인해서 "아는 기기"가 되는 것을 막기 위해서다.
    """

    __tablename__ = "user_devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_fingerprint", name="uq_user_devices_user_fingerprint"),
    )

    device_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    device_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(45))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
