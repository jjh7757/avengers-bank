from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class IdempotencyRecord(Base):
    """이체 요청의 Idempotency-Key. 같은 키로 다시 오면 돈을 다시 움직이지 않고 처음 결과를 돌려준다.
    response가 비어 있으면 처리 중이다. 성공한 이체만 남기고, 실패한 요청은 지워서 같은 키로 다시 시도할 수 있게 한다.
    타행 이체는 출금과 같은 트랜잭션에서 transfer_id를 적는다. 출금이 커밋된 키는 그 뒤 무슨 일이 나도 지우지 않고,
    다시 오면 그 타행 이체의 지금 상태를 돌려준다 (허브 호출 중 연결이 끊겨도 두 번 출금되지 않게)."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),)

    idempotency_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # 같은 키에 다른 내용이 오면 거절
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    transfer_id: Mapped[str | None] = mapped_column(String(36))  # 출금이 커밋된 타행 이체 (interbank_transfers)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
