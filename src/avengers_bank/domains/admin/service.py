"""관리자 자금 관리: 금고 현금·허브 예치금 현황과 예치금 입금·인출 신청.

신청·취소·동기화 로직은 interbank/reserve_requests.py를 그대로 쓴다 (CLI와 같은 함수). 여기서는 권한 확인 뒤
감사 로그를 남기는 것만 더한다. 고객 계좌 잔액을 바꾸는 경로는 없다: 움직이는 것은 금고 현금(CASH_VAULT)과
예치금(HUB_RESERVE) 두 내부 계정뿐이다.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.clock import now_utc
from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.admin.models import AdminAction, AdminAuditLog, AuditResult
from avengers_bank.domains.interbank import reserve_requests as rr
from avengers_bank.domains.interbank.hub_client import hub_client
from avengers_bank.domains.interbank.models import HubReserveRequest, LedgerAccount, ReserveRequestStatus
from avengers_bank.domains.interbank.service import ledger_balances, reconcile
from avengers_bank.domains.users.models import User

logger = logging.getLogger(__name__)

HUB_FIELDS = ("bank_code", "balance", "net_debit_cap", "exposure", "available")


class InterbankDisabled(ApiException):
    def __init__(self):
        super().__init__(status_code=503, code="INTERBANK_DISABLED",
                         message="허브(ClearingHub) 설정이 없어 예치금을 신청할 수 없습니다.")


def _require_hub() -> None:
    if not get_settings().interbank_enabled:
        raise InterbankDisabled()


# ---- 감사 로그 ----

async def write_audit(db: AsyncSession, *, admin_user_id: int, action: AdminAction, result: AuditResult,
                      target: str | None = None, detail: dict | None = None, error_code: str | None = None,
                      client_ip: str | None = None, rollback: bool = False) -> None:
    """본 작업과 따로 커밋한다. 본 작업이 예외로 끝났으면(rollback=True) 남은 트랜잭션을 먼저 롤백하고 남긴다
    (이체의 FDS 거절 기록 transfers/service.py _raise_rejection과 같은 방식). 성공이면 남은 트랜잭션은 커밋한다
    (롤백하면 응답에 쓸 객체가 만료된다. reserve_requests 함수들은 바꾼 것을 이미 스스로 커밋한다)."""
    if db.in_transaction():
        await (db.rollback() if rollback else db.commit())
    async with db.begin():
        db.add(AdminAuditLog(admin_user_id=admin_user_id, action=action, target=target, detail=detail or {},
                             result=result, error_code=error_code, client_ip=client_ip, created_at=now_utc()))


async def _audited(db: AsyncSession, admin_user_id: int, action: AdminAction, client_ip: str | None,
                   detail: dict, run: Callable[[], Awaitable[Any]],
                   summarize: Callable[[Any], tuple[str | None, dict, str | None]],
                   target: str | None = None) -> Any:
    """run()을 하고 결과를 감사 로그에 남긴다. 예외면 FAILED(오류 코드)로 남기고 그대로 던진다.
    summarize(결과) → (target, 더할 detail, 실패 코드 또는 None)."""
    try:
        value = await run()
    except Exception as exc:
        code = exc.code if isinstance(exc, ApiException) else "INTERNAL_ERROR"
        await write_audit(db, admin_user_id=admin_user_id, action=action, result=AuditResult.FAILED, target=target,
                          detail=detail, error_code=code, client_ip=client_ip, rollback=True)
        raise
    target, extra, failed_code = summarize(value)
    await write_audit(db, admin_user_id=admin_user_id, action=action,
                      result=AuditResult.FAILED if failed_code else AuditResult.OK, target=target,
                      detail={**detail, **extra}, error_code=failed_code, client_ip=client_ip)
    return value


def _hub_failure(req: HubReserveRequest) -> str | None:
    """허브가 접수 전에 4xx로 거절한 신청(FAILED)이면 허브 오류 코드 (reject_reason = "코드: 설명")."""
    if req.status != ReserveRequestStatus.FAILED:
        return None
    return (req.reject_reason or "HUB_REJECTED").split(":", 1)[0][:64]


def _request_summary(req: HubReserveRequest) -> tuple[str, dict, str | None]:
    return str(req.request_id), {"status": req.status, "hub_request_id": req.hub_request_id}, _hub_failure(req)


async def create_reserve_request(db: AsyncSession, admin_user_id: int, kind: str, amount: int, memo: str,
                                 client_ip: str | None) -> HubReserveRequest:
    async def run():
        _require_hub()
        return await rr.request(db, kind, amount, memo)  # 입금이면 금고 잔액 검사를 잠근 채로 한다 (_deposit_guard)

    return await _audited(db, admin_user_id, AdminAction.RESERVE_REQUEST_CREATE, client_ip,
                          {"kind": kind, "amount": amount, "memo": memo}, run, _request_summary)


async def cancel_reserve_request(db: AsyncSession, admin_user_id: int, request_id: int,
                                 client_ip: str | None) -> HubReserveRequest:
    async def run():
        _require_hub()
        return await rr.cancel(db, request_id)

    def summarize(req: HubReserveRequest):
        return str(req.request_id), {"kind": req.kind, "amount": req.amount, "status": req.status}, None

    return await _audited(db, admin_user_id, AdminAction.RESERVE_REQUEST_CANCEL, client_ip, {}, run, summarize,
                          target=str(request_id))


async def sync_reserve_requests(db: AsyncSession, admin_user_id: int, client_ip: str | None) -> list[HubReserveRequest]:
    async def run():
        _require_hub()
        return await rr.sync(db)

    def summarize(changed: list[HubReserveRequest]):
        return None, {"changed": [{"request_id": r.request_id, "status": r.status} for r in changed]}, None

    return await _audited(db, admin_user_id, AdminAction.RESERVE_SYNC, client_ip, {}, run, summarize)


async def list_reserve_requests(db: AsyncSession, limit: int = 50) -> list[HubReserveRequest]:
    async with db.begin():
        return await rr.list_requests(db, limit)


async def list_audit_logs(db: AsyncSession, limit: int) -> list[tuple[AdminAuditLog, str]]:
    async with db.begin():
        rows = await db.execute(
            select(AdminAuditLog, User.login_id).join(User, User.user_id == AdminAuditLog.admin_user_id)
            .order_by(AdminAuditLog.log_id.desc()).limit(limit)
        )
        return [(log, login_id) for log, login_id in rows]


# ---- 현황 ----

async def _hub_reserve() -> tuple[dict | None, str | None]:
    """허브가 말하는 우리 예치금 (SPEC 10.2 GET /v1/reserve). 못 받으면 (None, 이유 코드)."""
    if not get_settings().interbank_enabled:
        return None, "INTERBANK_DISABLED"
    reply = await hub_client.reserve()
    if not reply.ok:
        logger.warning("허브 예치금 조회 실패: HTTP %s %s", reply.status, reply.error)
        return None, reply.error
    return {key: reply.body.get(key) for key in HUB_FIELDS}, None


async def treasury(db: AsyncSession) -> dict:
    # 허브 호출은 DB 트랜잭션 밖에서 먼저 한다 (허브가 느려도 DB 연결을 붙잡지 않게)
    hub, hub_error = await _hub_reserve()
    problems = await reconcile(db)  # 자기 트랜잭션을 연다
    async with db.begin():
        balances = await ledger_balances(db)
        vault = await rr._vault_balance(db)
        open_deposits = await rr._open_deposits(db)
        open_rows = (await db.scalars(select(HubReserveRequest.kind).where(HubReserveRequest.status.in_(rr.OPEN)))).all()
    return {
        "vault_cash": vault,
        "ledger_hub_reserve": balances.get(LedgerAccount.HUB_RESERVE.value, 0),
        "hub_reserve": hub,
        "hub_reserve_error": hub_error,
        "open_deposit_amount": open_deposits,
        "deposit_available": max(vault - open_deposits, 0),
        "open_request_count": len(open_rows),
        "open_deposit_count": sum(1 for kind in open_rows if kind == "DEPOSIT"),
        "open_withdraw_count": sum(1 for kind in open_rows if kind == "WITHDRAW"),
        "suspense_balance": balances.get(LedgerAccount.SUSPENSE.value, 0),
        "reconcile_problems": problems,
        "interbank_enabled": get_settings().interbank_enabled,
        "checked_at": now_utc(),
    }
