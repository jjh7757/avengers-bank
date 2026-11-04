from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionResponse(BaseModel):
    session_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    input_mode: Literal["text", "voice"] = "text"


class ChatMessageResponse(BaseModel):
    msg_id: int
    role: str
    content: str
    intent: str | None
    input_mode: str
    card: dict | None
    screen: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatReplyResponse(BaseModel):
    """POST /chat/sessions/{id}/messages — 저장된 사용자 메시지와 에이전트 답변"""

    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse
