"""우리 은행 → 허브 호출 (SPEC 3절). 서명을 붙이고, 응답 없음·거절·성공을 하나의 결과로 돌려준다."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from avengers_bank.core.config import get_settings
from avengers_bank.domains.interbank.signing import sign

logger = logging.getLogger(__name__)


@dataclass
class HubReply:
    status: int | None  # None = 응답 없음 (타임아웃·연결 실패)
    body: dict[str, Any]

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


class HubClient:
    """테스트에서는 `_client`에 가짜 허브(ASGITransport)를 붙인 httpx 클라이언트를 넣는다."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def _request(self, method: str, path: str, payload: dict | None = None) -> HubReply:
        settings = get_settings()
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() if payload is not None else b""
        headers = {
            "X-Bank-Code": settings.bank_code,
            "X-Api-Key": settings.hub_api_key.get_secret_value(),
            "Content-Type": "application/json; charset=utf-8",
            **sign(settings.hub_secret.get_secret_value(), body),
        }
        url = settings.hub_url.rstrip("/") + "/v1" + path
        timeout = settings.hub_timeout_seconds
        try:
            # ASGITransport(테스트)에는 httpx 타임아웃이 걸리지 않으므로 wait_for로 한 번 더 감싼다
            response = await asyncio.wait_for(
                self.client.request(method, url, content=body, headers=headers, timeout=timeout), timeout
            )
        except (TimeoutError, httpx.HTTPError) as exc:
            logger.warning("허브 응답 없음: %s %s (%s)", method, path, type(exc).__name__)
            return HubReply(None, {})
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        return HubReply(response.status_code, data if isinstance(data, dict) else {})

    async def banks(self) -> HubReply:
        return await self._request("GET", "/banks")

    async def inquiry(self, to_bank: str, to_account: str) -> HubReply:
        return await self._request("POST", "/inquiry", {"to_bank": to_bank, "to_account": to_account})

    async def transfer(self, payload: dict) -> HubReply:
        return await self._request("POST", "/transfers", payload)

    async def get_transfer(self, transfer_id: str) -> HubReply:
        return await self._request("GET", f"/transfers/{transfer_id}")


hub_client = HubClient()
