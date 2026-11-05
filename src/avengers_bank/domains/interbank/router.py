"""허브 → 우리 은행 API (SPEC 4절). 응답은 SPEC 5절 형식({"error", "message"})이라 앱의 기본 오류 형식을 쓰지 않는다.
서명을 원문 바이트로 검증해야 하므로 본문은 직접 읽어 검증한 뒤 Pydantic으로 푼다."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import get_db
from avengers_bank.domains.interbank import service
from avengers_bank.domains.interbank.signing import HUB_BANK_CODE, verify

router = APIRouter(prefix="/interbank", tags=["interbank (허브 전용)"])
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
    error = verify(settings.hub_secret.get_secret_value(), request.headers.get("x-timestamp"), body,
                   request.headers.get("x-signature"))
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
