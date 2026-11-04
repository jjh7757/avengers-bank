from typing import Any

from pydantic import BaseModel, Field


class SuccessResponse[T](BaseModel):
    data: T
    message: str | None = None


class ValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[ValidationIssue] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorDetail


ERROR_EXAMPLES = {
    400: ("BAD_REQUEST", "요청을 처리할 수 없습니다."),
    401: ("UNAUTHORIZED", "인증이 필요합니다."),
    403: ("FORBIDDEN", "접근 권한이 없습니다."),
    404: ("NOT_FOUND", "요청한 리소스를 찾을 수 없습니다."),
    409: ("CONFLICT", "요청이 현재 상태와 충돌합니다."),
    422: ("VALIDATION_ERROR", "입력값을 확인해 주세요."),
    500: ("INTERNAL_SERVER_ERROR", "서버에서 오류가 발생했습니다."),
}


def error_responses(*status_codes: int) -> dict[int, dict[str, Any]]:
    responses = {}
    for status_code in status_codes:
        code, message = ERROR_EXAMPLES[status_code]
        example = ErrorResponse(error=ErrorDetail(code=code, message=message))
        responses[status_code] = {
            "model": ErrorResponse,
            "description": message,
            "content": {"application/json": {"example": example.model_dump()}},
        }
    return responses
