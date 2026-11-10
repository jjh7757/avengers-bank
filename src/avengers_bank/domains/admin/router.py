from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import require_admin
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.admin import service
from avengers_bank.domains.admin.schemas import (
    AuditLogResponse,
    ReserveRequestCreate,
    ReserveRequestResponse,
    TreasuryResponse,
)
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/admin", tags=["admin"], responses=error_responses(401, 403))

Db = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[UserResponse, Depends(require_admin)]


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/treasury", response_model=SuccessResponse[TreasuryResponse])
async def get_treasury(db: Db, admin: Admin):
    """금고 현금·허브 예치금(우리 장부와 허브 양쪽)·신청 가능 금액·대사 결과."""
    return SuccessResponse[TreasuryResponse](data=TreasuryResponse.model_validate(await service.treasury(db)))


@router.get("/treasury/reserve-requests", response_model=SuccessResponse[list[ReserveRequestResponse]])
async def list_reserve_requests(db: Db, admin: Admin):
    """최근 예치금 신청 50건 (최신순)."""
    rows = await service.list_reserve_requests(db)
    return SuccessResponse[list[ReserveRequestResponse]](data=[ReserveRequestResponse.model_validate(r) for r in rows])


@router.post(
    "/treasury/reserve-requests", status_code=201, response_model=SuccessResponse[ReserveRequestResponse],
    responses=error_responses(400, 422),
)
async def create_reserve_request(data: ReserveRequestCreate, db: Db, admin: Admin, request: Request):
    """허브 예치금 입금·인출 신청. 허브 관리자가 승인해야 잔액이 바뀐다.
    허브가 접수 전에 거절하면 201과 status FAILED(reject_reason), 허브가 응답하지 않으면 SENDING(동기화가 다시 보낸다)."""
    req = await service.create_reserve_request(db, admin.user_id, data.kind, data.amount, data.memo, _ip(request))
    return SuccessResponse[ReserveRequestResponse](data=ReserveRequestResponse.model_validate(req),
                                                   message="예치금 신청을 보냈습니다.")


@router.post(
    "/treasury/reserve-requests/sync", response_model=SuccessResponse[list[ReserveRequestResponse]],
)
async def sync_reserve_requests(db: Db, admin: Admin, request: Request):
    """열린 신청을 지금 허브와 맞춘다 (승인이면 장부 반영). 상태가 바뀐 신청 목록."""
    changed = await service.sync_reserve_requests(db, admin.user_id, _ip(request))
    return SuccessResponse[list[ReserveRequestResponse]](data=[ReserveRequestResponse.model_validate(r) for r in changed])


@router.post(
    "/treasury/reserve-requests/{request_id}/cancel", response_model=SuccessResponse[ReserveRequestResponse],
    responses=error_responses(404, 409),
)
async def cancel_reserve_request(request_id: int, db: Db, admin: Admin, request: Request):
    """결정 전 신청 취소. 그사이 허브가 이미 승인했으면 승인으로 맞추고(장부 반영) 그 상태를 돌려준다."""
    req = await service.cancel_reserve_request(db, admin.user_id, request_id, _ip(request))
    return SuccessResponse[ReserveRequestResponse](data=ReserveRequestResponse.model_validate(req))


@router.get("/audit-logs", response_model=SuccessResponse[list[AuditLogResponse]])
async def list_audit_logs(db: Db, admin: Admin, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    """관리자 행동 기록 (최신순, 실패한 시도 포함)."""
    rows = await service.list_audit_logs(db, limit)
    return SuccessResponse[list[AuditLogResponse]](data=[
        AuditLogResponse(admin_login_id=login_id, **{k: getattr(log, k) for k in (
            "log_id", "admin_user_id", "action", "target", "detail", "result", "error_code", "client_ip", "created_at")})
        for log, login_id in rows
    ])
