from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class ChatSessionResponse(BaseModel):
    session_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


from avengers_bank.agents.state import Screen

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
ParamValue = int | Annotated[str, StringConstraints(max_length=30)]


class UiSelected(BaseModel):
    """모아 화면에서 사용자가 눌러 고른 항목"""

    kind: Literal["account", "card", "product"]
    label: Label
    account_type: Literal["checking", "deposit", "savings"] | None = None
    account_id: int | None = None
    card_type: Literal["credit", "debit"] | None = None
    card_id: int | None = None
    product_kind: Literal["account", "card"] | None = None
    product_id: int | None = None


class UiContext(BaseModel):
    """지금 사용자가 보고 있는 화면 (모아 화면만 보낸다). 에이전트가 "이거", "이 계좌"를 풀 때 쓴다"""

    screen: Screen | None = None
    screen_params: dict[Annotated[str, StringConstraints(max_length=20)], ParamValue] = Field(default_factory=dict, max_length=5)
    selected: UiSelected | None = None
    visible: list[Label] = Field(default_factory=list, max_length=10, description="화면에 보이는 항목 이름 (위에서부터)")


class ChatMessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    ui_context: UiContext | None = None


class ChatMessageResponse(BaseModel):
    msg_id: int
    role: str
    content: str
    intent: str | None
    card: dict | None
    screen: str | None = None
    screen_params: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatReplyResponse(BaseModel):
    """POST /chat/sessions/{id}/messages — 저장된 사용자 메시지와 에이전트 답변"""

    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse
