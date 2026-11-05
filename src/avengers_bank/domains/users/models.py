from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
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
    # 이번 로그인과 그 전 로그인. 화면에 "지난 로그인"을 보여 줘서 모르는 접속을 알아채게 한다
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def has_pin(self) -> bool:
        return self.hashed_pin is not None


class RefreshToken(Base):
    """로그인 유지용 refresh 토큰. 값은 httpOnly 쿠키로만 주고 DB에는 SHA-256 해시만 둔다.
    쓸 때마다 새 토큰으로 바꾸고(회전), 이미 바꾼 토큰이 다시 오면 탈취로 보고 그 사용자의 토큰을 모두 끊는다."""

    __tablename__ = "refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # rotated: 새 토큰으로 바뀜(동시 갱신 유예 대상) / logout / reuse: 재사용 감지로 모두 끊음
    revoke_reason: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
