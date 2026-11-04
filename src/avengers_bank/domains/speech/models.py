from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class VoiceProfile(Base):
    """등록한 목소리 (화자 인증). 원본 녹음은 저장하지 않고 화자 임베딩만 암호화해 둔다.

    목소리 특징은 개인정보보호법상 민감정보(생체정보)다. 별도 동의를 받고, 사용자가 언제든 지울 수 있다.
    """

    __tablename__ = "voice_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), primary_key=True)
    embedding_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # Fernet(float32 벡터)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
