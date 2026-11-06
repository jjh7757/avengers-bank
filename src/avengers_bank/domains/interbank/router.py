"""허브 → 우리 은행 API (SPEC 4절). 응답은 SPEC 5절 형식({"error", "message"})이라 앱의 기본 오류 형식을 쓰지 않는다.
서명을 원문 바이트로 검증해야 하므로 본문은 직접 읽어 검증한 뒤 Pydantic으로 푼다.

서명 검증 (SPEC 2.2): 허브 공개키(HUB_PUBLIC_KEY)로 Ed25519만. `X-Signature-Alg`는 `ed25519`이거나 없어야 하고(없으면 ed25519),
그 밖의 값(예전 `hmac` 포함)은 401 SIGNATURE_INVALID. 서명 헤더가 없으면 401 UNAUTHORIZED (SPEC 5절).
응답 서명(SPEC 2.5)은 response_signing.py 미들웨어가 붙인다. 입금·입금 확인의 요청·응답 원문은 hub_evidence에 남긴다."""

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
from avengers_bank.domains.interbank.evidence import record_receive_in
from avengers_bank.domains.interbank.hub_client import REQUEST_EVIDENCE_HEADERS
from avengers_bank.domains.interbank.response_signing import EVIDENCE_SCOPE_KEY
from avengers_bank.domains.interbank.signing import ALG_ED25519, ALG_HEADER, HUB_BANK_CODE, verify_ed25519

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


def _spec_path(request: Request) -> str:
    """서명 경로는 base_url(`.../interbank`) 뒤의 부분이다 (SPEC 2.2). 운영에서는 /api 아래에 마운트되므로
    실제 경로(/api/interbank/receive)가 아니라 규격 경로(/receive)로 검증한다."""
    return request.url.path.partition(router.prefix)[2]


async def _verified_body(request: Request) -> bytes | JSONResponse:
    settings = get_settings()
    if not settings.interbank_receive_enabled:  # HUB_API_KEY 없이도 받는다 (셀프 등록 직후 ping, config)
        return _error(503, "INTERBANK_DISABLED", "다른 은행 이체가 설정되지 않았습니다")
    if request.headers.get("x-bank-code") != HUB_BANK_CODE:
        return _error(401, "UNAUTHORIZED", "허브 요청이 아닙니다")
    timestamp, signature = request.headers.get("x-timestamp"), request.headers.get("x-signature")
    if not (timestamp and signature):
        return _error(401, "UNAUTHORIZED", "서명 헤더가 없습니다")
    alg = (request.headers.get(ALG_HEADER) or ALG_ED25519).strip().lower()
    if alg != ALG_ED25519:
        return _error(401, "SIGNATURE_INVALID", f"지원하지 않는 서명 방식입니다 ({ALG_HEADER}: ed25519만): {alg[:20]}")
    body = await request.body()
    error = verify_ed25519(settings.hub_public_key, timestamp, request.method, _spec_path(request), body, signature)
    if error:
        return _error(401, error, "서명이 맞지 않습니다" if error == "SIGNATURE_INVALID" else "서명 시각이 만료됐습니다")
    return body


async def _keep_evidence(request: Request, db: AsyncSession, transfer_id: str, body: bytes) -> None:
    """검증을 통과한 입금·입금 확인 요청의 원문을 처리 전에 남기고(RECEIVE_IN), 우리 응답(RECEIVE_REPLY)은
    응답 서명 미들웨어가 서명한 뒤 남기게 표시한다 (같은 요청 scope로 transfer_id를 넘긴다)."""
    headers = {name: request.headers[name] for name in REQUEST_EVIDENCE_HEADERS if name in request.headers}
    async with db.begin():
        record_receive_in(db, transfer_id[:36], request.method, _spec_path(request), headers, body, ALG_ED25519)
    holder = request.scope.get(EVIDENCE_SCOPE_KEY)
    if holder is not None:
        holder["transfer_id"] = transfer_id[:36]


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
    await _keep_evidence(request, db, data.transfer_id, body)
    status, content = await service.receive(db, data.model_dump())
    return JSONResponse(status_code=status, content=content)


@router.get("/receive/{transfer_id}")
async def receive_status(transfer_id: str, request: Request, db: Db):
    body = await _verified_body(request)
    if isinstance(body, JSONResponse):
        return body
    await _keep_evidence(request, db, transfer_id, body)
    result = await service.receipt_status(db, transfer_id)
    if result is None:
        return _error(404, "TRANSFER_NOT_FOUND", "그 거래 ID로 입금한 적이 없습니다", transfer_id)
    return result
