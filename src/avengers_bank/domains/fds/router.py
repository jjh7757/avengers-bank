from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.fds.schemas import FdsLogResponse
from avengers_bank.domains.fds.service import fds_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/fds", tags=["fds"], responses=error_responses(401, 422))


@router.get("/logs", response_model=SuccessResponse[list[FdsLogResponse]])
async def get_my_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """내 FDS 판정 기록 (최근 순). 대시보드·발표용."""
    logs = await fds_service.get_my_logs(db, current_user.user_id, limit)
    return SuccessResponse[list[FdsLogResponse]](data=logs)
