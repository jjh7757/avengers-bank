from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.recipients.schemas import (
    RecipientCreate,
    RecipientResponse,
    RecipientUpdate,
)
from avengers_bank.domains.recipients.service import recipient_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/recipients", tags=["recipients"], responses=error_responses(401, 422))

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]


@router.get("", response_model=SuccessResponse[list[RecipientResponse]])
async def get_my_recipients(db: Db, current_user: CurrentUser, nickname: str | None = None):
    recipients = await recipient_service.get_my_recipients(db, current_user, nickname)
    return SuccessResponse[list[RecipientResponse]](data=recipients)


@router.post(
    "",
    response_model=SuccessResponse[RecipientResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(404, 409),
)
async def create_recipient(data: RecipientCreate, db: Db, current_user: CurrentUser):
    recipient = await recipient_service.create(db, data, current_user)
    return SuccessResponse[RecipientResponse](data=recipient, message="수취인이 등록되었습니다.")


@router.patch(
    "/{recipient_id}",
    response_model=SuccessResponse[RecipientResponse],
    responses=error_responses(403, 404, 409),
)
async def update_recipient(
    recipient_id: int, data: RecipientUpdate, db: Db, current_user: CurrentUser
):
    recipient = await recipient_service.update(db, recipient_id, data, current_user)
    return SuccessResponse[RecipientResponse](data=recipient, message="수취인 이름이 변경되었습니다.")


@router.delete(
    "/{recipient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(403, 404),
)
async def delete_recipient(recipient_id: int, db: Db, current_user: CurrentUser):
    await recipient_service.delete(db, recipient_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
