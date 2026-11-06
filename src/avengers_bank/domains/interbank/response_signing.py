"""`/interbank/*` 응답 서명 미들웨어 (SPEC 2.5). ClearingHub의 `core/response_signing.py`와 같은 방식을 이 저장소 안에 둔다.

message = X-Response-Timestamp + "\\n" + STATUS + "\\n" + 요청의 X-Signature 값 + "\\n" + 응답 본문 바이트
헤더   = X-Response-Timestamp, X-Response-Signature, X-Signature-Alg: ed25519

- 2xx·4xx 응답(서명 검증 실패 401 포함)에 붙인다. SPEC 2.5에서 필수다: 없거나 틀리면 허브가 그 응답을 "응답 없음"으로 보고
  이체가 PENDING에 쌓인다. 키(INTERBANK_SIGNING_KEY)는 타행 이체를 켜는 조건이라 켜져 있으면 늘 있다.
  키가 없으면(타행 이체 꺼짐, 503 INTERBANK_DISABLED) 서명하지 않는다.
- 5xx는 붙이지 않는다 (본문 보장이 없다, SPEC 5절). 본문은 한 바이트도 바꾸지 않는다.
- 본문을 다 모아야 서명할 수 있으므로, 여러 조각으로 나오는 스트리밍 응답은 서명 없이 그대로 흘려보낸다.
  `/interbank/*` 응답은 모두 한 조각(JSONResponse)이다.
- 순수 ASGI 미들웨어라 요청 본문은 건드리지 않는다 (요청 서명 검증은 본문 바이트 그대로 한다).
- 증거: router가 scope[EVIDENCE_SCOPE_KEY]에 transfer_id를 넣은 요청(/receive, /receive/{id})은 서명한 응답을
  보내기 직전에 hub_evidence(RECEIVE_REPLY)에 남긴다. 키가 없어도 응답 원문은 남긴다.
- 서명한 뒤 본문을 바꾸는 미들웨어(압축 등)를 이것보다 안쪽에 두지 않는다 (main.py에서 가장 먼저 단다).
"""

from collections.abc import Awaitable, Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from avengers_bank.domains.interbank.signing import sign_response

EVIDENCE_SCOPE_KEY = "avengers_bank.interbank_evidence"  # router가 {"transfer_id": ...}를 채운다

ReplyRecorder = Callable[[str, int, dict[str, str], bytes], Awaitable[None]]


def _route_path(scope: Scope) -> str:
    """마운트(/api)를 뺀 경로. Starlette는 scope["path"]에 root_path를 포함해 넘긴다."""
    path, root = scope.get("path", ""), scope.get("root_path", "")
    return path[len(root):] if root and path.startswith(root) else path


class ResponseSigningMiddleware:
    def __init__(self, app: ASGIApp, key_getter: Callable[[], str | None], path_prefix: str = "/interbank/",
                 record_reply: ReplyRecorder | None = None) -> None:
        self.app = app
        self.key_getter = key_getter  # 개인키 base64. 요청마다 읽는다 (없으면 서명하지 않음)
        self.path_prefix = path_prefix
        self.record_reply = record_reply

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _route_path(scope).startswith(self.path_prefix):
            await self.app(scope, receive, send)
            return
        holder: dict[str, str] = {}
        scope[EVIDENCE_SCOPE_KEY] = holder
        request_signature = next(
            (value.decode("latin-1") for name, value in scope.get("headers", []) if name == b"x-signature"), ""
        )
        start: Message | None = None
        key: str | None = None
        passthrough = False

        async def send_signed(message: Message) -> None:
            nonlocal start, key, passthrough
            if passthrough:
                await send(message)
                return
            if message["type"] == "http.response.start":
                key = self.key_getter()
                record = self.record_reply is not None and "transfer_id" in holder
                if message["status"] >= 500 or not (key or record):
                    passthrough = True
                    await send(message)
                else:
                    start = message  # 본문을 보고 서명한 뒤 보낸다
                return
            if message["type"] == "http.response.body" and start is not None:
                if message.get("more_body", False):  # 스트리밍: 서명 없이 그대로
                    passthrough = True
                    await send(start)
                    await send(message)
                    return
                body = message.get("body", b"")
                signed = sign_response(key, start["status"], request_signature, body) if key else {}
                names = {name.lower().encode("latin-1") for name in signed}
                headers = [(k, v) for k, v in start.get("headers", []) if k.lower() not in names]
                headers += [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in signed.items()]
                if self.record_reply is not None and "transfer_id" in holder:
                    await self.record_reply(holder["transfer_id"], start["status"], signed, body)
                await send({**start, "headers": headers})
                start = None
                passthrough = True
                await send(message)
                return
            await send(message)

        await self.app(scope, receive, send_signed)
