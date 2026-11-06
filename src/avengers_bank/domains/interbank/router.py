"""허브 → 우리 은행 API (SPEC 4절). 응답은 SPEC 5절 형식({"error", "message"})이라 앱의 기본 오류 형식을 쓰지 않는다.
서명을 원문 바이트로 검증해야 하므로 본문은 직접 읽어 검증한 뒤 Pydantic으로 푼다."""

import logging
import sys
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import get_db
from avengers_bank.domains.interbank import service
from avengers_bank.domains.interbank.signing import HUB_BANK_CODE, verify

logger = logging.getLogger(__name__)


class SpecErrorRoute(APIRoute):
    """처리하지 못한 예외도 SPEC 5절 형식(`{"error": "INTERNAL_ERROR", "message"}`)의 500으로 답한다.
    앱 기본 처리기는 앱 형식(`{"error": {"code"...}}`)으로 답하므로 허브 전용 경로만 여기서 감싼다.
    허브는 5xx면 재시도한다 (SPEC 4.2 규칙 4). 입금은 transfer_id로 멱등이라 재시도해도 한 번만 들어간다."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def spec_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except Exception as exc:
                logger.exception("허브 요청 처리 실패: %s %s", request.method, request.url.path)
                sentry = sys.modules.get("sentry_sdk")  # 켜져 있을 때만 (core/sentry.py). 삼켰으니 직접 보낸다
                if sentry is not None:
                    sentry.capture_exception(exc)
                return _error(500, "INTERNAL_ERROR", "은행 서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")

        return spec_handler


router = APIRouter(prefix="/interbank", tags=["interbank (허브 전용)"], route_class=SpecErrorRoute)
Db = Annotated[AsyncSession, Depends(get_db)]


class InquiryBody(BaseModel):
    account_num: str = Field(min_length=1, max_length=50)


class ReceiveBody(BaseModel):
    transfer_id: str = Field(min_length=1, max_length=36)
    from_bank: str = Field(pattern=r"^\d{3}$")
    from_bank_name: str = Field(default="", max_length=50)
    from_account: str = Field(min_length=1, max_length=50)
    to_account: str = Field(min_length=1, max_length=50)
    amount: int = Field(gt=0, strict=True)
    sender_name: str = Field(min_length=1, max_length=50)
    memo: str = Field(default="", max_length=100)


def _error(status: int, code: str, message: str, transfer_id: str | None = None) -> JSONResponse:
    body = {"error": code, "message": message}
    if transfer_id:
        body["transfer_id"] = transfer_id
    return JSONResponse(status_code=status, content=body)


async def _verified_body(request: Request) -> bytes | JSONResponse:
    settings = get_settings()
    if not settings.interbank_enabled:
        return _error(503, "INTERBANK_DISABLED", "다른 은행 이체가 설정되지 않았습니다")
    if request.headers.get("x-bank-code") != HUB_BANK_CODE:
        return _error(401, "UNAUTHORIZED", "허브 요청이 아닙니다")
    body = await request.body()
    # 서명 경로는 base_url(`.../interbank`) 뒤의 부분이다 (SPEC 2.2). 운영에서는 /api 아래에 마운트되므로
    # 실제 경로(/api/interbank/receive)가 아니라 규격 경로(/receive)로 검증한다
    spec_path = request.url.path.partition(router.prefix)[2]
    error = verify(settings.hub_secret.get_secret_value(), request.headers.get("x-timestamp"), request.method,
                   spec_path, body, request.headers.get("x-signature"))
    if error:
        return _error(401, error, "서명이 맞지 않습니다" if error == "SIGNATURE_INVALID" else "서명 시각이 만료됐습니다")
    return body


def _validation_error(exc: ValidationError) -> JSONResponse:
    fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
    return _error(422, "VALIDATION_ERROR", f"입력값을 확인해 주세요: {fields}")


@router.post("/inquiry")
async def inquiry(request: Request, db: Db):
    body = await _verified_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        data = InquiryBody.model_validate_json(body)
    except ValidationError as exc:
        return _validation_error(exc)
    name = await service.holder_name_of(db, data.account_num)
    if name is None:
        return _error(404, "ACCOUNT_NOT_FOUND", "받는 계좌를 찾을 수 없습니다")
    return {"holder_name": name}


class AccountsBody(BaseModel):
    ci: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/accounts")
async def accounts(request: Request, db: Db):
    """본인 명의 계좌 조회 (SPEC 9.4): 이 CI를 가진 고객의 입출금 계좌. 고객이 없어도 200 빈 목록."""
    body = await _verified_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        data = AccountsBody.model_validate_json(body)
    except ValidationError as exc:
        return _validation_error(exc)
    return {"accounts": await service.own_accounts_by_ci(db, data.ci)}


@router.post("/receive")
async def receive(request: Request, db: Db):
    body = await _verified_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        data = ReceiveBody.model_validate_json(body)
    except ValidationError as exc:
        return _validation_error(exc)
    status, content = await service.receive(db, data.model_dump())
    return JSONResponse(status_code=status, content=content)


@router.get("/receive/{transfer_id}")
async def receive_status(transfer_id: str, request: Request, db: Db):
    body = await _verified_body(request)
    if isinstance(body, JSONResponse):
        return body
    result = await service.receipt_status(db, transfer_id)
    if result is None:
        return _error(404, "TRANSFER_NOT_FOUND", "그 거래 ID로 입금한 적이 없습니다", transfer_id)
    return result
