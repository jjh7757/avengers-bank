"""구조화(JSON) 로깅과 요청 ID.

- 요청마다 request ID를 정한다. 들어온 `X-Request-ID`가 안전한 형식이면 그대로 쓰고, 없으면 새로 만든다.
  응답 헤더에도 같은 값을 붙여, 사용자가 알려 준 ID로 서버 로그를 바로 찾을 수 있게 한다.
- 로그 한 줄이 JSON 하나다 (CloudWatch·Loki 같은 곳에서 필드로 검색). 그 요청 안에서 남긴 로그에는 request_id가 저절로 붙는다.
- 요청이 끝나면 접근 로그 한 줄: method, path, status, duration_ms, client.

설정 (.env 또는 환경변수, core/config.py와 따로 읽는다)
- LOG_LEVEL: 기본 INFO
- LOG_FORMAT: json(기본) 또는 text (로컬에서 사람이 읽기 편한 형식)
"""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from avengers_bank.core.responses import ErrorDetail, ErrorResponse

REQUEST_ID_HEADER = "X-Request-ID"
# 받은 값을 로그에 그대로 쓰므로 줄바꿈·따옴표 같은 문자는 받지 않는다 (로그 위조 방지)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
# 헬스체크는 모니터링이 수십 초마다 부르므로 접근 로그를 DEBUG로 낮춘다
_QUIET_PATHS = {"/health", "/api/health"}
_HANDLER_NAME = "avengers_bank"

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
access_logger = logging.getLogger("avengers_bank.access")
logger = logging.getLogger(__name__)


class LoggingSettings(BaseSettings):
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_logging_settings() -> LoggingSettings:
    return LoggingSettings()


def get_request_id() -> str | None:
    """지금 처리 중인 요청의 ID (요청 밖이면 None)"""
    return request_id_var.get()


# LogRecord가 원래 가진 속성. 이 밖의 값(logger.info(..., extra={...}))만 JSON 필드로 옮긴다
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            entry["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in entry:
                entry[key] = value
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = getattr(record, "request_id", None) or get_request_id() or "-"
        return super().format(record)


def configure_logging() -> None:
    """루트 로거에 핸들러를 하나 단다. 여러 번 불러도 한 번만 단다.
    uvicorn 자체 로거(uvicorn.*)는 uvicorn 설정을 그대로 둔다."""
    settings = get_logging_settings()
    root = logging.getLogger()
    if any(h.get_name() == _HANDLER_NAME for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter() if settings.log_format == "json" else TextFormatter())
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            candidate = value.decode("latin-1").strip()
            return candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else None
    return None


class RequestContextMiddleware:
    """request ID를 정하고 응답 헤더에 붙이며, 요청이 끝나면 접근 로그를 남긴다.

    순수 ASGI 미들웨어라 스트리밍 응답도 그대로 흘려보낸다. 운영(prod.py)은 바깥 앱과 /api에 마운트한 앱 양쪽에
    달려 있는데, 바깥에서 이미 ID를 정했으면 안쪽은 아무것도 하지 않는다 (로그가 두 번 남지 않게).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or request_id_var.get() is not None:
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # 처리하지 못한 예외: 응답이 아직 안 나갔으면 여기서 500을 보내야 X-Request-ID가 붙는다
            logger.error("처리하지 못한 요청 오류: %s %s", scope.get("method"), scope.get("path"), exc_info=True)
            if not response_started:
                await _send_internal_error(send_with_request_id)
            raise
        finally:
            path = scope.get("path", "")
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            client = scope.get("client")
            access_logger.log(
                logging.DEBUG if path in _QUIET_PATHS and status < 500 else logging.INFO,
                "%s %s %s %.1fms",
                scope.get("method"),
                path,
                status,
                duration_ms,
                extra={
                    "request_id": request_id,
                    "method": scope.get("method"),
                    "path": path,
                    "status": status,
                    "duration_ms": duration_ms,
                    "client": client[0] if client else None,
                },
            )
            request_id_var.reset(token)


async def _send_internal_error(send: Send) -> None:
    # core/exception_handlers.py의 500 응답과 같은 모양
    error = ErrorResponse(error=ErrorDetail(code="INTERNAL_SERVER_ERROR", message="서버에서 오류가 발생했습니다."))
    body = error.model_dump_json().encode()
    await send({
        "type": "http.response.start",
        "status": 500,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


__all__ = [
    "REQUEST_ID_HEADER",
    "JsonFormatter",
    "RequestContextMiddleware",
    "configure_logging",
    "get_request_id",
]
