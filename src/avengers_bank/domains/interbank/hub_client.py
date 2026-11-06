"""우리 은행 → 허브 호출 (SPEC 3절). 서명을 붙이고, 응답 없음·거절·성공을 하나의 결과로 돌려준다.

서명은 Ed25519 하나다 (SPEC 2절): 요청은 우리 개인키(INTERBANK_SIGNING_KEY)로 서명하고 `X-Signature-Alg: ed25519`를 붙인다.
허브의 2xx·4xx 응답에는 허브 응답 서명(SPEC 2.5)이 **항상** 있어야 하고, 허브 공개키(HUB_PUBLIC_KEY)로 검증한다.
없거나 틀리면 "응답 없음"으로 바꾼다: 본문을 믿지 않고 결과를 모르는 상태로 둔다 (되돌리지 않고 3.4로 확인, SPEC 6절).
4xx를 거절로 믿고 되돌렸는데 실제로는 허브가 접수했다면 돈이 두 배가 되기 때문이다.
5xx는 본문 보장이 없어(SPEC 5절) 서명을 요구하지 않고 그대로 돌려준다.

예외: 셀프 등록(`register_bank`, SPEC 3.5)은 서명 없이 보내고, 응답 서명이 틀려도 본문을 버리지 않는다(signature_valid만 False).
api_key가 그 응답에만 있어서, 버리면 초대 코드는 쓰였는데 키를 잃는다. 판단은 keys 도구가 사람에게 넘긴다.
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
    ALG_ED25519, ALG_HEADER, RESPONSE_SIGNATURE_HEADER, RESPONSE_TIMESTAMP_HEADER, sign_ed25519, verify_response,
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
    status: int | None  # None = 응답 없음 (타임아웃·연결 실패, 2xx·4xx인데 허브 응답 서명이 없거나 틀림)
    body: dict[str, Any]
    # 허브 응답 서명 검증 결과: True 맞음, False 없음·틀림, None 응답을 못 받음 또는 5xx(서명을 요구하지 않음)
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


def _sign(method: str, path: str, body: bytes) -> dict[str, str]:
    """우리 개인키로 Ed25519 서명 (SPEC 2.2). 키는 타행 이체가 켜진 조건이라(interbank_enabled) 여기서는 늘 있다."""
    key = get_settings().interbank_signing_key
    if key is None:
        raise RuntimeError("INTERBANK_SIGNING_KEY가 없어 허브 요청에 서명할 수 없습니다")
    return sign_ed25519(key.get_secret_value(), method, path, body)


def _check_reply_signature(response: httpx.Response, request_signature: str) -> bool:
    """허브 응답 서명(SPEC 2.5)을 허브 공개키로 검증한다. 서명 헤더가 없거나 방식이 ed25519가 아니면 False."""
    signature = response.headers.get(RESPONSE_SIGNATURE_HEADER)
    if not signature:
        return False
    if (response.headers.get(ALG_HEADER) or ALG_ED25519).strip().lower() != ALG_ED25519:
        return False
    error = verify_response(get_settings().hub_public_key, response.headers.get(RESPONSE_TIMESTAMP_HEADER),
                            response.status_code, request_signature, response.content, signature)
    return error is None


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json() if response.content else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class HubClient:
    """테스트에서는 `_client`에 가짜 허브(ASGITransport)를 붙인 httpx 클라이언트를 넣는다."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def _send(self, method: str, spec_path: str, body: bytes, headers: dict[str, str]
                    ) -> tuple[httpx.Response | None, HubExchange]:
        """보내고, 오간 바이트를 HubExchange로 남긴다. 응답이 없으면(타임아웃·연결 실패) response는 None."""
        settings = get_settings()
        # 추적 ID (SPEC 2.4, 서명 대상 아님): 이 요청의 ID를 허브에 넘기면 허브가 받는 은행까지 그대로 전달한다.
        # 처리 중 확인 태스크처럼 요청 밖에서 부르면 없고, 그때는 허브가 새로 만든다
        request_id = get_request_id()
        if request_id:
            headers[REQUEST_ID_HEADER] = request_id
        exchange = HubExchange(method, spec_path, _pick(headers, REQUEST_EVIDENCE_HEADERS), body,
                               headers.get(ALG_HEADER, ALG_ED25519))
        url = settings.hub_url.rstrip("/") + spec_path
        timeout = settings.hub_timeout_seconds
        try:
            # ASGITransport(테스트)에는 httpx 타임아웃이 걸리지 않으므로 wait_for로 한 번 더 감싼다
            response = await asyncio.wait_for(
                self.client.request(method, url, content=body, headers=headers, timeout=timeout), timeout
            )
        except (TimeoutError, httpx.HTTPError) as exc:
            logger.warning("허브 응답 없음: %s %s (%s)", method, spec_path, type(exc).__name__)
            return None, exchange
        exchange.response_status = response.status_code
        exchange.response_headers = _pick(response.headers, REPLY_EVIDENCE_HEADERS)
        exchange.response_body = response.content
        return response, exchange

    async def _request(self, method: str, path: str, payload: dict | None = None) -> HubReply:
        settings = get_settings()
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() if payload is not None else b""
        spec_path = "/v1" + path  # SPEC 2.2
        headers = {
            "X-Bank-Code": settings.bank_code,
            "X-Api-Key": settings.hub_api_key.get_secret_value(),
            "Content-Type": "application/json; charset=utf-8",
            **_sign(method, spec_path, body),
        }
        response, exchange = await self._send(method, spec_path, body, headers)
        if response is None:
            return HubReply(None, {}, exchange=exchange)
        if response.status_code >= 500:
            return HubReply(response.status_code, _json(response), None, exchange)
        if not _check_reply_signature(response, headers["X-Signature"]):
            # 허브가 답했다고 증명할 수 없는 응답이다. 2xx라도 완료로, 4xx라도 거절로 믿지 않는다
            logger.error("허브 응답 서명 검증 실패: %s %s HTTP %s → 응답 없음으로 처리", method, spec_path,
                         response.status_code)
            return HubReply(None, {}, signature_valid=False, exchange=exchange)
        return HubReply(response.status_code, _json(response), True, exchange)

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

    async def ack_settlement(self, run_id: int) -> HubReply:
        """대사 일치를 알린다 (SPEC 10.8, 본문 없음). DRAFT에만. 포지션이 있는 은행이 모두 ack하면 그 자리에서 확정돼
        응답 status가 SETTLED다. SETTLED·CANCELLED면 409 SETTLEMENT_NOT_DRAFT"""
        return await self._request("POST", f"/settlements/{run_id}/ack")

    async def dispute_settlement(self, run_id: int, transfer_ids: list[str], message: str | None = None) -> HubReply:
        """대사 불일치를 알린다 (SPEC 10.8). 그 run은 자동 확정되지 않고 허브 관리자에게 알림이 간다. DRAFT에만"""
        payload: dict = {"transfer_ids": transfer_ids}
        if message:
            payload["message"] = message[:200]
        return await self._request("POST", f"/settlements/{run_id}/dispute", payload)

    async def register_key(self, public_key: str) -> HubReply:
        """내 공개키 교체 (SPEC 2.6 `PUT /v1/keys`). 지금(옛) 키로 서명한다. 허브는 옛 키를 24시간 더 받는다."""
        return await self._request("PUT", "/keys", {"public_key": public_key})

    async def key_status(self) -> HubReply:
        """내 공개키 등록 상태 (SPEC 2.6 `GET /v1/keys`)"""
        return await self._request("GET", "/keys")

    async def me(self) -> HubReply:
        """내 등록 정보: 코드·이름·base_url·활성·순채무한도·공개키 지문 (SPEC 3.6 `GET /v1/me`)"""
        return await self._request("GET", "/me")

    async def ping_me(self) -> HubReply:
        """허브가 지금 등록된 우리 base_url로 ping (SPEC 3.6 `POST /v1/me/ping`, 본문 없음).
        결과 {ok, reachable, status, body, response_signature_valid}"""
        return await self._request("POST", "/me/ping")

    async def register_bank(self, invite_code: str, name: str, base_url: str, public_key: str) -> HubReply:
        """셀프 등록 (SPEC 3.5 `POST /v1/banks/register`, 인증 없음 — 초대 코드가 인증이다). 서명 헤더를 붙이지 않는다.
        HUB_API_KEY가 아직 없을 때 부르므로 X-Bank-Code·X-Api-Key도 넣지 않는다.
        허브는 이 응답에도 서명한다(request_signature ""). 서명이 틀려도 본문은 버리지 않고 signature_valid만 False다
        (api_key가 이 응답에만 있다, 모듈 설명)."""
        payload = {"invite_code": invite_code, "name": name, "base_url": base_url, "public_key": public_key}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json; charset=utf-8"}
        response, exchange = await self._send("POST", "/v1/banks/register", body, headers)
        if response is None:
            return HubReply(None, {}, exchange=exchange)
        valid = None if response.status_code >= 500 else _check_reply_signature(response, "")
        if valid is False:
            logger.error("셀프 등록 응답의 허브 서명 검증 실패: HTTP %s", response.status_code)
        return HubReply(response.status_code, _json(response), valid, exchange)

    async def hub_key(self) -> HubReply:
        """허브 공개키 (SPEC 2.6 `GET /v1/hub-key`, 인증 없음). 응답 서명은 그 키로 하므로 여기서는 검증하지 않는다.
        받은 지문을 허브 관리자가 따로 알려 준 값과 사람이 맞춰 본다."""
        url = get_settings().hub_url.rstrip("/") + "/v1/hub-key"
        try:
            response = await self.client.get(url, timeout=get_settings().hub_timeout_seconds)
        except httpx.HTTPError as exc:
            logger.warning("허브 응답 없음: GET /hub-key (%s)", type(exc).__name__)
            return HubReply(None, {})
        return HubReply(response.status_code, _json(response))


hub_client = HubClient()
