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
    birth_date: Mapped[str | None] = mapped_column(String(8))  # YYYYMMDD. 본인 명의 계좌 조회(가상 CI)에 쓴다
    # 가상 CI (ClearingHub SPEC 9.1) = HMAC(CI_KEY, 이름|생년월일|휴대폰). 다른 은행이 같은 사람을 찾을 때 쓴다
    ci: Mapped[str | None] = mapped_column(String(64), index=True)
    hashed_pin: Mapped[str | None] = mapped_column(String(255))  # 이체 추가 인증용 6자리 PIN
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def has_pin(self) -> bool:
        return self.hashed_pin is not None
