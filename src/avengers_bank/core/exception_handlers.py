import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from avengers_bank.core.exceptions import ApiException
from avengers_bank.core.responses import ErrorDetail, ErrorResponse, ValidationIssue

logger = logging.getLogger(__name__)


async def api_exception_handler(request: Request, exc: ApiException) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=exc.code, message=exc.message))
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(mode="json"),
        headers=exc.headers,
    )


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        422: "VALIDATION_ERROR",
    }.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "요청을 처리할 수 없습니다."
    return await api_exception_handler(
        request, ApiException(exc.status_code, code, message, headers=exc.headers)
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        ValidationIssue(loc=list(error["loc"]), msg=error["msg"], type=error["type"])
        for error in exc.errors()
    ]
    body = ErrorResponse(
        error=ErrorDetail(
            code="VALIDATION_ERROR", message="입력값을 확인해 주세요.", details=details
        )
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("처리하지 못한 요청 오류: %s %s", request.method, request.url.path, exc_info=exc)
    return await api_exception_handler(
        request, ApiException(500, "INTERNAL_SERVER_ERROR", "서버에서 오류가 발생했습니다.")
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiException, api_exception_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
