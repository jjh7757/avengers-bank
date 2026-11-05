"""SPEC 2절: HMAC-SHA256 요청 서명 (허브와 같은 방식).

message   = X-Timestamp + "\\n" + body(전송 바이트 그대로)
signature = hex(HMAC-SHA256(secret, message))
"""

import hashlib
import hmac
import time

HUB_BANK_CODE = "000"  # 허브가 은행을 부를 때의 X-Bank-Code
MAX_SKEW_SECONDS = 300


def sign(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    sig = hmac.new(secret.encode(), ts.encode() + b"\n" + body, hashlib.sha256).hexdigest()
    return {"X-Timestamp": ts, "X-Signature": sig}


def verify(secret: str, timestamp: str | None, body: bytes, signature: str | None) -> str | None:
    """맞으면 None, 틀리면 오류 코드 (SIGNATURE_EXPIRED / SIGNATURE_INVALID)."""
    try:
        ts = int(timestamp or "")
    except ValueError:
        return "SIGNATURE_INVALID"
    if abs(int(time.time()) - ts) > MAX_SKEW_SECONDS:
        return "SIGNATURE_EXPIRED"
    expected = hmac.new(secret.encode(), str(ts).encode() + b"\n" + body, hashlib.sha256).hexdigest()
    return None if hmac.compare_digest(expected, signature or "") else "SIGNATURE_INVALID"
