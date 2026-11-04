from typing import Literal, TypedDict

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

Intent = Literal["inquiry", "transfer", "product", "card", "cancel", "general"]


class Extraction(BaseModel):
    """의도 분류기(LLM)의 구조화 출력"""

    intent: Intent
    recipient: str | None = Field(default=None, max_length=50)
    to_account_num: str | None = Field(default=None, max_length=20)
    amount: int | None = Field(default=None, gt=0)
    amount_text: str | None = Field(default=None, max_length=50)
    from_account_hint: str | None = Field(default=None, max_length=50)


class PendingTransfer(BaseModel):
    """여러 턴에 걸쳐 채우는 이체 정보. chat_sessions.state["pending_transfer"]에 저장된다."""

    recipient_nickname: str | None = None
    to_account_num: str | None = None
    holder_name: str | None = None
    amount: int | None = None
    from_checking_account_id: int | None = None


class AgentState(TypedDict, total=False):
    user_text: str
    history: list[BaseMessage]  # 이번 메시지 이전 대화
    pending: PendingTransfer | None
    extraction: Extraction
    messages: list[BaseMessage]  # 조회·상담 노드의 LLM ↔ 도구 대화
    tool_rounds: int
    # 출력
    reply: str
    card: dict | None
    new_pending: PendingTransfer | None
    confirmation_jti: str | None
