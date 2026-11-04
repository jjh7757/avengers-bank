from datetime import datetime

from pydantic import BaseModel, Field


class VoiceProfileResponse(BaseModel):
    enrolled: bool
    available: bool  # 서버에서 음성 승인을 쓸 수 있는지 (모델·암호화 키)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VoiceProfileDelete(BaseModel):
    password: str = Field(min_length=1, max_length=128, repr=False)


class VoiceApprovalResponse(BaseModel):
    voice_approval_token: str
