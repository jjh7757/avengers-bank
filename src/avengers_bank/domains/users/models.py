from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    login_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    nick_name: Mapped[str | None] = mapped_column(String(50))
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    hashed_pin: Mapped[str | None] = mapped_column(String(255))  # 이체 추가 인증용 6자리 PIN
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def has_pin(self) -> bool:
        return self.hashed_pin is not None
