"""우리 은행 → 허브 호출 (SPEC 3절). 서명을 붙이고, 응답 없음·거절·성공을 하나의 결과로 돌려준다.

서명 방식은 INTERBANK_SIGNATURE_MODE(허브 관리자가 우리에게 정한 모드와 같게 둔다)로 정한다 (SPEC 2절 표·2.6):
  hmac    → HMAC. 허브 응답 서명은 보지 않는다 (예전과 같다)
  both    → Ed25519(우리 키가 있으면, 없으면 HMAC). 허브 응답 서명은 있으면 검증해 signature_valid만 남긴다
  ed25519 → Ed25519. 허브 2xx·4xx 응답에 허브 응답 서명(SPEC 2.5)이 **반드시** 있어야 하고, 없거나 틀리면
            "응답 없음"으로 바꾼다. 본문을 믿지 않고 결과를 모르는 상태로 둔다 (되돌리지 않고 3.4로 확인, SPEC 6절).
            4xx를 거절로 믿고 되돌렸는데 실제로는 허브가 접수했다면 돈이 두 배가 되기 때문이다
5xx는 본문 보장이 없어(SPEC 5절) 서명을 요구하지 않고 그대로 돌려준다.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from avengers_bank.core.config import get_settings
from avengers_bank.core.logging import REQUEST_ID_HEADER, get_request_id
from avengers_bank.domains.interbank.signing import (
    ALG_ED25519, ALG_HEADER, ALG_HMAC, RESPONSE_SIGNATURE_HEADER, RESPONSE_TIMESTAMP_HEADER, sign, sign_ed25519,
    verify_response,
)

logger = logging.getLogger(__name__)

# 증거로 남길 헤더 (hub_evidence). 서명 검증에 필요한 것과 추적 ID만. X-Api-Key는 넣지 않는다
REQUEST_EVIDENCE_HEADERS = ("X-Bank-Code", "X-Timestamp", "X-Signature", ALG_HEADER, REQUEST_ID_HEADER)
REPLY_EVIDENCE_HEADERS = (RESPONSE_TIMESTAMP_HEADER, RESPONSE_SIGNATURE_HEADER, ALG_HEADER)


@dataclass
class HubExchange:
    """실제로 오간 바이트 (증거 보관용, evidence.py). 응답을 못 받았으면 response_status가 None."""

    method: str
    path: str  # 서명에 쓴 규격 경로 (/v1/...)
    request_headers: dict[str, str]
    request_body: bytes
    signature_alg: str
    response_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: bytes = b""


@dataclass
class HubReply:
    status: int | None  # None = 응답 없음 (타임아웃·연결 실패, ed25519 모드에서 허브 응답 서명이 없거나 틀림)
    body: dict[str, Any]
    # 허브 응답 서명 검증 결과: True 맞음, False 없음·틀림, None 보지 않음(hmac 모드)·서명 없음(both 모드)
    signature_valid: bool | None = None
    exchange: HubExchange | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def rejected(self) -> bool:
        """허브가 4xx로 거절: 최종 실패 (SPEC 3.3). 재시도하지 않는다."""
        return self.status is not None and 400 <= self.status < 500

    @property
    def error(self) -> str:
        return str(self.body.get("error") or ("HUB_TIMEOUT" if self.status is None else "HUB_ERROR"))

    @property
    def message(self) -> str:
        return str(self.body.get("message") or "")


def _pick(headers, names: tuple[str, ...]) -> dict[str, str]:
    return {name: headers[name] for name in names if headers.get(name) is not None}


def _sign(method: str, path: str, body: bytes, alg: str | None = None) -> dict[str, str]:
    """모드에 맞는 서명 헤더. alg를 주면 그 방식으로 (키 등록 PUT /v1/keys는 hmac·both 모드에서 HMAC, SPEC 2.6).
    hmac 모드는 예전과 똑같이 X-Signature-Alg를 붙이지 않는다 (없으면 허브가 HMAC으로 본다)."""
    settings = get_settings()
    key = settings.interbank_signing_key
    if alg is None:
        alg = ALG_HMAC if settings.interbank_signature_mode == "hmac" else ALG_ED25519
    if alg == ALG_ED25519:
        if key is not None:
            return sign_ed25519(key.get_secret_value(), method, path, body)
        # ed25519 모드는 시작할 때 키를 요구하므로(config) both 모드에서 키를 아직 넣지 않은 경우뿐이다
        logger.warning("INTERBANK_SIGNING_KEY가 없어 허브 요청에 HMAC으로 서명합니다 (%s 모드)", settings.interbank_signature_mode)
    headers = sign(settings.hub_secret.get_secret_value(), method, path, body)
    return headers if settings.interbank_signature_mode == "hmac" else {**headers, ALG_HEADER: ALG_HMAC}


def _check_reply_signature(response: httpx.Response, request_signature: str) -> bool | None:
    """허브 응답 서명(SPEC 2.5) 검증. hmac 모드는 보지 않는다(None). 서명 헤더가 없으면 ed25519 모드에서만 False."""
    settings = get_settings()
    mode = settings.interbank_signature_mode
    if mode == "hmac":
        return None
    signature = response.headers.get(RESPONSE_SIGNATURE_HEADER)
    if not signature:
        return False if mode == "ed25519" else None
    if (response.headers.get(ALG_HEADER) or ALG_ED25519).strip().lower() != ALG_ED25519:
        return False
    error = verify_response(settings.hub_public_key, response.headers.get(RESPONSE_TIMESTAMP_HEADER),
                            response.status_code, request_signature, response.content, signature)
    return error is None


class HubClient:
    """테스트에서는 `_client`에 가짜 허브(ASGITransport)를 붙인 httpx 클라이언트를 넣는다."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def _request(self, method: str, path: str, payload: dict | None = None, alg: str | None = None) -> HubReply:
        settings = get_settings()
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() if payload is not None else b""
        spec_path = "/v1" + path  # SPEC 2.2
        headers = {
            "X-Bank-Code": settings.bank_code,
            "X-Api-Key": settings.hub_api_key.get_secret_value(),
            "Content-Type": "application/json; charset=utf-8",
            **_sign(method, spec_path, body, alg),
        }
        # 추적 ID (SPEC 2.4, 서명 대상 아님): 이 요청의 ID를 허브에 넘기면 허브가 받는 은행까지 그대로 전달한다.
        # 처리 중 확인 태스크처럼 요청 밖에서 부르면 없고, 그때는 허브가 새로 만든다
        request_id = get_request_id()
        if request_id:
            headers[REQUEST_ID_HEADER] = request_id
        exchange = HubExchange(method, spec_path, _pick(headers, REQUEST_EVIDENCE_HEADERS), body,
                               headers.get(ALG_HEADER, ALG_HMAC))
        url = settings.hub_url.rstrip("/") + spec_path
        timeout = settings.hub_timeout_seconds
        try:
            # ASGITransport(테스트)에는 httpx 타임아웃이 걸리지 않으므로 wait_for로 한 번 더 감싼다
            response = await asyncio.wait_for(
                self.client.request(method, url, content=body, headers=headers, timeout=timeout), timeout
            )
        except (TimeoutError, httpx.HTTPError) as exc:
            logger.warning("허브 응답 없음: %s %s (%s)", method, path, type(exc).__name__)
            return HubReply(None, {}, exchange=exchange)
        exchange.response_status = response.status_code
        exchange.response_headers = _pick(response.headers, REPLY_EVIDENCE_HEADERS)
        exchange.response_body = response.content
        signature_valid = _check_reply_signature(response, headers["X-Signature"])
        if settings.interbank_signature_mode == "ed25519" and response.status_code < 500 and not signature_valid:
            # 허브가 답했다고 증명할 수 없는 응답이다. 2xx라도 완료로, 4xx라도 거절로 믿지 않는다
            logger.error("허브 응답 서명 검증 실패: %s %s HTTP %s → 응답 없음으로 처리", method, path, response.status_code)
            return HubReply(None, {}, signature_valid=False, exchange=exchange)
        if signature_valid is False:  # both 모드: 기록만 하고 동작은 바꾸지 않는다
            logger.warning("허브 응답 서명이 맞지 않습니다 (both 모드라 그대로 씀): %s %s HTTP %s", method, path,
                           response.status_code)
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        return HubReply(response.status_code, data if isinstance(data, dict) else {}, signature_valid, exchange)

    async def banks(self) -> HubReply:
        return await self._request("GET", "/banks")

    async def inquiry(self, to_bank: str, to_account: str) -> HubReply:
        return await self._request("POST", "/inquiry", {"to_bank": to_bank, "to_account": to_account})

    async def transfer(self, payload: dict) -> HubReply:
        return await self._request("POST", "/transfers", payload)

    async def get_transfer(self, transfer_id: str) -> HubReply:
        return await self._request("GET", f"/transfers/{transfer_id}")

    async def lookup_accounts(self, ci: str, consent_id: str) -> HubReply:
        """본인 명의 다른 은행 계좌 (SPEC 9.2)"""
        return await self._request("POST", "/accounts/lookup", {"ci": ci, "consent_id": consent_id})

    async def settlements(self) -> HubReply:
        """내 정산 목록: 최근 30일 run, 최신순, CANCELLED 제외 (SPEC 10.4)"""
        return await self._request("GET", "/settlements")

    async def settlement(self, run_id: int) -> HubReply:
        """대사 파일: 그 run의 내 포지션과 내가 보내거나 받은 거래 (SPEC 10.5). 서명 PATH에 run_id까지 들어간다"""
        return await self._request("GET", f"/settlements/{run_id}")

    async def register_key(self, public_key: str) -> HubReply:
        """내 공개키 등록·교체 (SPEC 2.6 `PUT /v1/keys`). 지금 인증으로 서명한다: hmac·both 모드는 HMAC
        (처음 등록할 때는 허브에 공개키가 없어 Ed25519를 못 받는다), ed25519 모드는 지금 설정된(옛) 키로."""
        alg = ALG_ED25519 if get_settings().interbank_signature_mode == "ed25519" else ALG_HMAC
        return await self._request("PUT", "/keys", {"public_key": public_key}, alg=alg)

    async def key_status(self) -> HubReply:
        """내 공개키 등록 상태 (SPEC 2.6 `GET /v1/keys`)"""
        return await self._request("GET", "/keys")

    async def hub_key(self) -> HubReply:
        """허브 공개키 (SPEC 2.6 `GET /v1/hub-key`, 인증 없음). 응답 서명은 그 키로 하므로 여기서는 검증하지 않는다.
        받은 지문을 허브 관리자가 따로 알려 준 값과 사람이 맞춰 본다."""
        url = get_settings().hub_url.rstrip("/") + "/v1/hub-key"
        try:
            response = await self.client.get(url, timeout=get_settings().hub_timeout_seconds)
        except httpx.HTTPError as exc:
            logger.warning("허브 응답 없음: GET /hub-key (%s)", type(exc).__name__)
            return HubReply(None, {})
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        return HubReply(response.status_code, data if isinstance(data, dict) else {})


hub_client = HubClient()
