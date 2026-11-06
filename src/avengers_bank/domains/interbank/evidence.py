"""허브와 주고받은 이체 원문 보관 (hub_evidence, SPEC 2.5 "보관"). 추가만 하고 고치거나 지우지 않는다.

남기는 것
  TRANSFER_OUT / TRANSFER_REPLY  우리 → 허브 POST /v1/transfers 요청과 허브 응답 (처음 보낼 때와 확인 중 재전송)
  RECEIVE_IN / RECEIVE_REPLY     허브 → 우리 /interbank/receive(처음·재시도)·/interbank/receive/{id} 요청과 우리 응답
결과 조회(GET /v1/transfers/{id})·수취 조회·대사 조회·본인 계좌 조회는 남기지 않는다 (이체 접수와 입금만).

허브는 같은 거래의 접수 요청·/receive 원문을 자기 쪽(transfer_evidence)에 남긴다. 분쟁 때 양쪽 원문을 맞대어,
우리가 보낸 요청에 허브가 무엇이라고 답했는지(허브 서명), 허브의 입금 요청에 우리가 무엇이라고 답했는지(우리 서명)를 보인다.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.clock import real_now_utc
from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank.hub_client import HubReply
from avengers_bank.domains.interbank.models import EvidenceDirection, HubEvidence
from avengers_bank.domains.interbank.signing import ALG_HEADER, RESPONSE_SIGNATURE_HEADER

logger = logging.getLogger(__name__)


def record_transfer_exchange(db: AsyncSession, transfer_id: str, reply: HubReply) -> None:
    """우리가 보낸 이체 접수 요청과 (받았으면) 허브 응답. 호출하는 쪽의 트랜잭션 안에서 부른다.
    응답의 signature_valid는 hub_client의 허브 응답 서명 검증 결과다. 응답을 못 받았으면 요청만 남긴다."""
    ex = reply.exchange
    if ex is None:  # 실제로 오간 것이 없는 응답 (테스트 대역)
        return
    now = real_now_utc()
    db.add(HubEvidence(
        transfer_id=transfer_id, direction=EvidenceDirection.TRANSFER_OUT, method=ex.method, path=ex.path,
        headers_json=ex.request_headers, body=ex.request_body, signature_alg=ex.signature_alg, signature_valid=None,
        created_at=now,
    ))
    if ex.response_status is None:
        return
    signed = bool(ex.response_headers.get(RESPONSE_SIGNATURE_HEADER))
    db.add(HubEvidence(
        transfer_id=transfer_id, direction=EvidenceDirection.TRANSFER_REPLY, http_status=ex.response_status,
        headers_json=ex.response_headers, body=ex.response_body,
        signature_alg=ex.response_headers.get(ALG_HEADER) if signed else None, signature_valid=reply.signature_valid,
        created_at=now,
    ))


def record_receive_in(db: AsyncSession, transfer_id: str, method: str, path: str, headers: dict[str, str],
                      body: bytes, signature_alg: str) -> None:
    """서명 검증을 통과한 허브 요청 (router가 입금 처리 전에 부른다). 통과한 것만 오므로 signature_valid는 True.
    서명이 틀린 요청은 누구나 보낼 수 있어 남기지 않는다 (표가 아무에게나 커지지 않게)."""
    db.add(HubEvidence(
        transfer_id=transfer_id, direction=EvidenceDirection.RECEIVE_IN, method=method, path=path,
        headers_json=headers, body=body, signature_alg=signature_alg, signature_valid=True, created_at=real_now_utc(),
    ))


async def record_receive_reply(transfer_id: str, status: int, headers: dict[str, str], body: bytes) -> None:
    """우리가 허브에 보낼 응답 (응답 서명 미들웨어가 보내기 직전에 부른다). 자기 세션으로 따로 커밋한다.
    입금은 이미 커밋됐으므로 여기서 실패해도 응답은 그대로 보낸다 (로그만 남긴다)."""
    signed = bool(headers.get(RESPONSE_SIGNATURE_HEADER))
    try:
        async with SessionLocal() as db, db.begin():
            db.add(HubEvidence(
                transfer_id=transfer_id, direction=EvidenceDirection.RECEIVE_REPLY, http_status=status,
                headers_json=headers, body=body, signature_alg=headers.get(ALG_HEADER) if signed else None,
                signature_valid=None, created_at=real_now_utc(),
            ))
    except Exception:
        logger.exception("허브 응답 증거 저장 실패: %s HTTP %s", transfer_id, status)


async def list_for_transfer(db: AsyncSession, transfer_id: str) -> list[HubEvidence]:
    """그 거래의 증거를 남긴 순서대로 (분쟁 조회·테스트용)."""
    async with db.begin():
        stmt = select(HubEvidence).where(HubEvidence.transfer_id == transfer_id).order_by(HubEvidence.evidence_id)
        return list(await db.scalars(stmt))
