from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.chat.schemas import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatReplyResponse,
    ChatSessionResponse,
)
from avengers_bank.domains.chat.service import chat_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/chat", tags=["chat"], responses=error_responses(401, 422))

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]


@router.post(
    "/sessions", response_model=SuccessResponse[ChatSessionResponse], status_code=status.HTTP_201_CREATED
)
async def create_session(db: Db, current_user: CurrentUser):
    session = await chat_service.create_session(db, current_user)
    return SuccessResponse[ChatSessionResponse](data=session)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=SuccessResponse[ChatReplyResponse],
    responses=error_responses(403, 404),
)
async def send_message(session_id: str, data: ChatMessageCreate, db: Db, current_user: CurrentUser):
    """에이전트에게 말하기. 답변에 확인 카드(card)가 있으면 프론트가 승인 버튼을 보여 주고,
    승인 시 카드의 값과 confirmation_token, session_id를 그대로 POST /transfers에 보낸다.
    Gemini를 쓸 수 없으면 503 `LLM_UNAVAILABLE`."""
    user_message, assistant_message = await chat_service.send_message(db, session_id, data, current_user)
    return SuccessResponse[ChatReplyResponse](
        data=ChatReplyResponse(
            user_message=ChatMessageResponse.model_validate(user_message),
            assistant_message=ChatMessageResponse.model_validate(assistant_message),
        )
    )


@router.get(
    "/sessions/{session_id}/messages",
    response_model=SuccessResponse[list[ChatMessageResponse]],
    responses=error_responses(403, 404),
)
async def get_messages(session_id: str, db: Db, current_user: CurrentUser):
    messages = await chat_service.get_messages(db, session_id, current_user)
    return SuccessResponse[list[ChatMessageResponse]](data=messages)
