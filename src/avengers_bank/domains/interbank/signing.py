"""SPEC 2절: HMAC-SHA256 요청 서명 (허브와 같은 방식).

message   = X-Timestamp + "\\n" + METHOD + "\\n" + PATH + "\\n" + body(전송 바이트 그대로)
signature = hex(HMAC-SHA256(secret, message))

METHOD는 대문자. PATH는 규격에 정한 경로다 (SPEC 2.2): 허브 API는 `/v1/...`,
우리 은행 API는 base_url(`.../interbank`) 뒤의 부분(`/receive` 등). 쿼리스트링은 넣지 않는다.
"""

import hashlib
import hmac
import time

HUB_BANK_CODE = "000"  # 허브가 은행을 부를 때의 X-Bank-Code
MAX_SKEW_SECONDS = 300


def _digest(secret: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    message = f"{timestamp}\n{method.upper()}\n{path}\n".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def sign(secret: str, method: str, path: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    return {"X-Timestamp": ts, "X-Signature": _digest(secret, ts, method, path, body)}


def verify(
    secret: str, timestamp: str | None, method: str, path: str, body: bytes, signature: str | None
) -> str | None:
    """맞으면 None, 틀리면 오류 코드 (SIGNATURE_EXPIRED / SIGNATURE_INVALID)."""
    try:
        ts = int(timestamp or "")
    except ValueError:
        return "SIGNATURE_INVALID"
    if abs(int(time.time()) - ts) > MAX_SKEW_SECONDS:
        return "SIGNATURE_EXPIRED"
    expected = _digest(secret, timestamp or "", method, path, body)
    try:
        return None if hmac.compare_digest(expected.encode(), (signature or "").encode("ascii")) else "SIGNATURE_INVALID"
    except UnicodeEncodeError:  # 비 ASCII 서명 헤더는 예외(500) 대신 401
        return "SIGNATURE_INVALID"
