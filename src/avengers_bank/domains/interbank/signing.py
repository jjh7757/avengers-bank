"""SPEC 2절: Ed25519 요청 서명과 응답 서명(2.5). 허브와 같은 방식. 서명 방식은 이것 하나다 (HMAC은 SPEC v1.0에서 빠졌다).

요청 message = X-Timestamp + "\\n" + METHOD + "\\n" + PATH + "\\n" + body(전송 바이트 그대로)
  X-Signature = base64(Ed25519(보내는 쪽 개인키, message)), X-Signature-Alg: ed25519 (SPEC 2.2·2.3)

METHOD는 대문자. PATH는 규격에 정한 경로다 (SPEC 2.2): 허브 API는 `/v1/...`,
우리 은행 API는 base_url(`.../interbank`) 뒤의 부분(`/receive` 등). 쿼리스트링은 넣지 않는다.

응답 message = X-Response-Timestamp + "\\n" + STATUS + "\\n" + 요청의 X-Signature 값 + "\\n" + 응답 body (SPEC 2.5)
  응답을 그 요청에 묶는다. 다른 요청에 대한 진짜 응답을 가져다 붙이면 검증이 틀린다.

키 표현 (SPEC 2.2·2.6): 개인키·공개키 모두 raw 32바이트의 표준 base64(패딩 포함, 44자). 서명은 raw 64바이트의 base64(88자).
지문 = sha256(raw 공개키)의 hex 앞 16자. 허브 공개키를 처음 받을 때 허브 관리자가 따로 알려 준 지문과 맞춰 본다.

검증 함수는 모두 맞으면 None, 아니면 오류 코드(SIGNATURE_EXPIRED / SIGNATURE_INVALID)를 돌려준다.
키·서명이 base64가 아니거나 길이가 틀려도 예외(500) 대신 SIGNATURE_INVALID(401)다.
"""

import base64
import binascii
import hashlib
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

HUB_BANK_CODE = "000"  # 허브가 은행을 부를 때의 X-Bank-Code
MAX_SKEW_SECONDS = 300

# 헤더 이름 (SPEC 2.1·2.5)
ALG_HEADER = "X-Signature-Alg"
RESPONSE_TIMESTAMP_HEADER = "X-Response-Timestamp"
RESPONSE_SIGNATURE_HEADER = "X-Response-Signature"
ALG_ED25519 = "ed25519"

KEY_B64_LENGTH = 44  # 32바이트 → base64 44자
SIGNATURE_B64_LENGTH = 88  # 64바이트 → base64 88자


def _message(timestamp: str, method: str, path: str, body: bytes) -> bytes:
    return f"{timestamp}\n{method.upper()}\n{path}\n".encode() + body


def _timestamp(timestamp: int | None) -> str:
    return str(int(time.time()) if timestamp is None else timestamp)


def _check_time(timestamp: str | None, max_skew: int | None) -> str | None:
    """시각 헤더가 숫자가 아니면 SIGNATURE_INVALID, 허용 오차를 넘으면 SIGNATURE_EXPIRED.
    max_skew None은 시각을 보지 않는다 (보관한 증거를 나중에 다시 검증할 때)."""
    try:
        ts = int(timestamp or "")
    except ValueError:
        return "SIGNATURE_INVALID"
    if max_skew is not None and abs(int(time.time()) - ts) > max_skew:
        return "SIGNATURE_EXPIRED"
    return None


# ── Ed25519 키 (SPEC 2.6) ─────────────────────────────────────────

def _b64decode(value: str | None, length: int) -> bytes | None:
    """표준 base64(패딩 포함)를 엄격하게 풀어 정확히 length 바이트일 때만 돌려준다. 그 밖에는 None."""
    if not isinstance(value, str) or len(value) != (KEY_B64_LENGTH if length == 32 else SIGNATURE_B64_LENGTH):
        return None
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        return None
    return raw if len(raw) == length else None


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def is_valid_key(key_b64: str | None) -> bool:
    """raw 32바이트의 표준 base64(44자)인지 (개인키·공개키 공통). 설정 검사에 쓴다."""
    return _b64decode(key_b64, 32) is not None


def _private_key(private_key_b64: str) -> Ed25519PrivateKey:
    raw = _b64decode(private_key_b64.strip(), 32)
    if raw is None:
        raise ValueError("Ed25519 개인키는 raw 32바이트의 base64(44자)여야 합니다")
    return Ed25519PrivateKey.from_private_bytes(raw)


def generate_keypair() -> tuple[str, str]:
    """(개인키 base64, 공개키 base64). 개인키는 우리 서버 환경 변수에만 두고, 공개키만 허브에 등록한다."""
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return _b64(private), _b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def public_key_of(private_key_b64: str) -> str:
    return _b64(_private_key(private_key_b64).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def fingerprint(public_key_b64: str) -> str:
    """sha256(raw 공개키) hex 앞 16자. 공개키 형식이 틀리면 ValueError."""
    raw = _b64decode(public_key_b64, 32)
    if raw is None:
        raise ValueError("Ed25519 공개키는 raw 32바이트의 base64(44자)여야 합니다")
    return hashlib.sha256(raw).hexdigest()[:16]


def _ed25519_sign(private_key_b64: str, message: bytes) -> str:
    return _b64(_private_key(private_key_b64).sign(message))


def _ed25519_verify(public_key_b64: str | None, message: bytes, signature_b64: str | None) -> bool:
    raw_key, raw_sig = _b64decode(public_key_b64, 32), _b64decode(signature_b64, 64)
    if raw_key is None or raw_sig is None:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(raw_key).verify(raw_sig, message)
    except (InvalidSignature, ValueError):
        return False
    return True


# ── Ed25519 요청 서명 (SPEC 2.3) ──────────────────────────────────

def sign_ed25519(private_key_b64: str, method: str, path: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts = _timestamp(timestamp)
    return {"X-Timestamp": ts, "X-Signature": _ed25519_sign(private_key_b64, _message(ts, method, path, body)),
            ALG_HEADER: ALG_ED25519}


def verify_ed25519(
    public_key_b64: str | None, timestamp: str | None, method: str, path: str, body: bytes, signature: str | None,
    max_skew: int | None = MAX_SKEW_SECONDS,
) -> str | None:
    """맞으면 None, 틀리면 오류 코드 (SIGNATURE_EXPIRED / SIGNATURE_INVALID). 잘못된 키·서명도 예외 없이 SIGNATURE_INVALID."""
    if error := _check_time(timestamp, max_skew):
        return error
    ok = _ed25519_verify(public_key_b64, _message(timestamp or "", method, path, body), signature)
    return None if ok else "SIGNATURE_INVALID"


# ── 응답 서명 (SPEC 2.5) ──────────────────────────────────────────

def _response_message(timestamp: str, status: int, request_signature: str, body: bytes) -> bytes:
    return f"{timestamp}\n{status}\n{request_signature}\n".encode() + body


def sign_response(
    private_key_b64: str, status: int, request_signature: str, body: bytes, timestamp: int | None = None
) -> dict[str, str]:
    """`request_signature`는 그 요청의 X-Signature 값 그대로 (서명 없는 요청이면 "", SPEC 2.5)."""
    ts = _timestamp(timestamp)
    signature = _ed25519_sign(private_key_b64, _response_message(ts, status, request_signature, body))
    return {RESPONSE_TIMESTAMP_HEADER: ts, RESPONSE_SIGNATURE_HEADER: signature, ALG_HEADER: ALG_ED25519}


def verify_response(
    public_key_b64: str | None, timestamp: str | None, status: int, request_signature: str, body: bytes,
    signature: str | None, max_skew: int | None = MAX_SKEW_SECONDS,
) -> str | None:
    """맞으면 None. 헤더 없음·형식 오류·불일치는 SIGNATURE_INVALID, 시각 초과는 SIGNATURE_EXPIRED."""
    if not timestamp or not signature:
        return "SIGNATURE_INVALID"
    if error := _check_time(timestamp, max_skew):
        return error
    message = _response_message(timestamp, status, request_signature, body)
    return None if _ed25519_verify(public_key_b64, message, signature) else "SIGNATURE_INVALID"
