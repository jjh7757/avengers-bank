"""허브 예치금 입금·인출 신청 (ClearingHub SPEC 10.9).

허브 예치금은 우리가 허브(중앙은행 역할)에 맡긴 돈이다. 우리는 신청만 하고, 허브 관리자가 승인해야 허브 잔액이
바뀐다. 승인을 확인하면 우리 장부도 같은 금액을 옮긴다 (한 번만):

  입금 승인   금고 현금(CASH_VAULT) −a / 예치금(HUB_RESERVE) +a    "reserve:{id}" RESERVE_MOVE
  인출 승인   예치금(HUB_RESERVE)   −a / 금고 현금(CASH_VAULT) +a

둘 다 "우리가 가진 돈" 계정이라 고객 잔액은 바뀌지 않는다. 입금은 금고 현금 안에서만 신청한다
(금고 현금 − 결정을 기다리는 입금 신청 합). 인출 한도(잔액 − 미정산 순채무)는 허브가 검사한다.

흐름
1. request: 행을 SENDING으로 남기고 커밋 → 허브 POST /v1/reserve/requests (request_ref로 멱등)
     2xx → PENDING(hub_request_id) / 4xx → FAILED(오류 코드·설명) / 응답 없음·5xx → SENDING 그대로 (sync가 다시 보낸다)
2. sync (confirm_loop가 주기적으로, 열린 신청이 있을 때만): SENDING은 다시 보내고, PENDING은 GET으로 결정을 확인한다
     APPROVED → 같은 트랜잭션에서 RESERVE_MOVE 분개 + booked_at / REJECTED·CANCELLED → 상태만
3. cancel: 허브에 취소를 보내고 결과대로 상태를 맞춘다 (이미 승인됐으면 승인으로 맞춘다)

운영 도구 (서버 컨테이너 안에서):

    python -m avengers_bank.domains.interbank.reserve_requests deposit 5000000 --memo "11월 예치"
    python -m avengers_bank.domains.interbank.reserve_requests withdraw 1000000
    python -m avengers_bank.domains.interbank.reserve_requests list
    python -m avengers_bank.domains.interbank.reserve_requests sync
    python -m avengers_bank.domains.interbank.reserve_requests cancel <id>
"""

import argparse
import asyncio
import logging
import selectors
import sys
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.clock import now_utc
from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException, BadRequestException, NotFoundException
from avengers_bank.domains.interbank.hub_client import HubReply, hub_client
from avengers_bank.domains.interbank.models import (
    HubReserveRequest, InterbankLedgerEntry, LedgerAccount, LedgerEvent, ReserveRequestStatus,
)
from avengers_bank.domains.interbank.service import _post

logger = logging.getLogger(__name__)

KINDS = ("DEPOSIT", "WITHDRAW")
MAX_AMOUNT = 1_000_000_000_000  # 허브 상한과 같다 (SPEC 10.9)
OPEN = (ReserveRequestStatus.SENDING, ReserveRequestStatus.PENDING)


def move_id(request_id: int) -> str:
    return f"reserve:{request_id}"


async def _vault_balance(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.coalesce(func.sum(InterbankLedgerEntry.amount), 0))
                               .where(InterbankLedgerEntry.account == LedgerAccount.CASH_VAULT)))


async def _open_deposits(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.coalesce(func.sum(HubReserveRequest.amount), 0)).where(
        HubReserveRequest.kind == "DEPOSIT", HubReserveRequest.status.in_(OPEN))))


async def _send(db: AsyncSession, req: HubReserveRequest) -> HubReserveRequest:
    """SENDING 신청을 허브에 보내고 결과대로 상태를 바꿔 커밋한다."""
    reply = await hub_client.create_reserve_request(req.request_ref, req.kind, req.amount, req.memo)
    if reply.ok:
        _apply_hub(db, req, reply.body)
        if req.status == ReserveRequestStatus.APPROVED:  # 다시 보냈는데 그사이 이미 승인됐다
            _book(db, req)
    elif reply.rejected:
        req.status = ReserveRequestStatus.FAILED
        req.reject_reason = f"{reply.error}: {reply.message}"[:300]
        req.decided_at = now_utc()
        logger.warning("허브가 예치금 신청 %s을 거절: %s", req.request_ref, req.reject_reason)
    else:
        logger.warning("허브 예치금 신청 %s 응답 없음 (%s). 다음 확인 때 다시 보낸다", req.request_ref, reply.error)
    await db.commit()
    return req


def _apply_hub(db: AsyncSession, req: HubReserveRequest, body: dict) -> None:
    """허브 신청 응답(SPEC 10.9)을 우리 행에 옮긴다. 분개는 하지 않는다 (_book)."""
    req.hub_request_id = int(body["request_id"])
    status = body.get("status")
    if status in (ReserveRequestStatus.PENDING, ReserveRequestStatus.APPROVED, ReserveRequestStatus.REJECTED,
                  ReserveRequestStatus.CANCELLED):
        req.status = status
    if status != ReserveRequestStatus.PENDING:
        req.decided_at = req.decided_at or now_utc()
    if status == ReserveRequestStatus.REJECTED:
        req.reject_reason = (body.get("reject_reason") or "")[:300]
    if body.get("balance_after") is not None:
        req.hub_balance_after = int(body["balance_after"])


def _book(db: AsyncSession, req: HubReserveRequest) -> None:
    """승인된 신청의 RESERVE_MOVE 분개 (한 번만). 유니크 제약(transfer_id, event, account)이 두 번째를 막는다."""
    if req.booked_at is not None:
        return
    sign = 1 if req.kind == "DEPOSIT" else -1
    _post(db, move_id(req.request_id), LedgerEvent.RESERVE_MOVE, get_settings().bank_code,
          (LedgerAccount.HUB_RESERVE, sign * req.amount), (LedgerAccount.CASH_VAULT, -sign * req.amount))
    req.booked_at = now_utc()
    logger.info("허브 예치금 %s 승인 반영: %s원 (신청 %s, 허브 잔액 %s원)",
                "입금" if sign > 0 else "인출", f"{req.amount:,}", req.request_ref, req.hub_balance_after)


async def request(db: AsyncSession, kind: str, amount: int, memo: str = "") -> HubReserveRequest:
    """신청을 남기고 허브에 보낸다. 입금은 금고 현금 − 결정을 기다리는 입금 신청 합까지만."""
    if kind not in KINDS:
        raise BadRequestException(code="VALIDATION_ERROR", message="kind는 DEPOSIT 또는 WITHDRAW입니다.")
    if not 1 <= amount <= MAX_AMOUNT:
        raise BadRequestException(code="VALIDATION_ERROR", message="금액은 1원 이상 1조 원 이하입니다.")
    if len(memo) > 200:
        raise BadRequestException(code="VALIDATION_ERROR", message="메모는 200자까지입니다.")
    if kind == "DEPOSIT":
        room = await _vault_balance(db) - await _open_deposits(db)
        if amount > room:
            raise BadRequestException(code="INSUFFICIENT_VAULT_CASH",
                                      message=f"금고 현금이 모자랍니다 (신청할 수 있는 금액 {max(room, 0):,}원).")
    req = HubReserveRequest(request_ref=f"avb-{uuid.uuid4().hex[:24]}", kind=kind, amount=amount, memo=memo,
                            status=ReserveRequestStatus.SENDING, created_at=now_utc())
    db.add(req)
    await db.commit()  # 허브에 보내기 전에 남긴다: 응답을 못 받아도 같은 request_ref로 다시 보낼 수 있게
    return await _send(db, req)


async def _refresh(db: AsyncSession, req: HubReserveRequest) -> None:
    reply = await hub_client.reserve_request(req.hub_request_id)
    if not reply.ok:
        if reply.status is not None:
            logger.warning("허브 예치금 신청 %s 조회 실패: HTTP %s %s", req.request_ref, reply.status, reply.error)
        return
    _apply_hub(db, req, reply.body)
    if req.status == ReserveRequestStatus.APPROVED:
        _book(db, req)
    await db.commit()


async def sync(db: AsyncSession) -> list[HubReserveRequest]:
    """열린(SENDING·PENDING) 신청을 허브와 맞춘다. 상태가 바뀐 신청 목록."""
    rows = list((await db.scalars(select(HubReserveRequest).where(HubReserveRequest.status.in_(OPEN))
                                  .order_by(HubReserveRequest.request_id))).all())
    changed = []
    for req in rows:
        before = req.status
        if req.status == ReserveRequestStatus.SENDING:
            await _send(db, req)
        else:
            await _refresh(db, req)
        if req.status != before:
            changed.append(req)
    return changed


async def cancel(db: AsyncSession, request_id: int) -> HubReserveRequest:
    req = await db.get(HubReserveRequest, request_id)
    if req is None:
        raise NotFoundException(code="RESERVE_REQUEST_NOT_FOUND", message="신청을 찾을 수 없습니다.")
    if req.status not in OPEN:
        raise ApiException(status_code=409, code="RESERVE_REQUEST_NOT_PENDING",
                           message=f"이미 {req.status} 상태입니다.")
    if req.hub_request_id is None:  # 허브 접수를 아직 모른다: 먼저 보내서 번호를 받는다 (같은 request_ref라 한 건)
        await _send(db, req)
        if req.status != ReserveRequestStatus.PENDING:
            return req
    reply = await hub_client.cancel_reserve_request(req.hub_request_id)
    if reply.ok:
        _apply_hub(db, req, reply.body)
        await db.commit()
    elif reply.status == 409:  # 그사이 결정됐다: 실제 상태로 맞춘다 (승인이면 분개까지)
        await _refresh(db, req)
    else:
        raise ApiException(status_code=503, code="HUB_UNAVAILABLE", message="허브에 취소를 보내지 못했습니다.")
    return req


async def list_requests(db: AsyncSession, limit: int = 50) -> list[HubReserveRequest]:
    return list((await db.scalars(select(HubReserveRequest).order_by(HubReserveRequest.request_id.desc())
                                  .limit(limit))).all())


async def has_open(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(func.count()).select_from(HubReserveRequest)
                                .where(HubReserveRequest.status.in_(OPEN))))


# ---- 운영 도구 ----

def _line(req: HubReserveRequest) -> str:
    label = "입금" if req.kind == "DEPOSIT" else "인출"
    extra = f" 허브 #{req.hub_request_id}" if req.hub_request_id else ""
    if req.reject_reason:
        extra += f" 사유: {req.reject_reason}"
    if req.hub_balance_after is not None:
        extra += f" 허브 잔액 {req.hub_balance_after:,}원"
    return f"#{req.request_id} {label} {req.amount:,}원 {req.status}{extra} ({req.request_ref})"


async def _cli(argv: list[str]) -> int:
    from avengers_bank.core.database import SessionLocal, engine

    parser = argparse.ArgumentParser(prog="python -m avengers_bank.domains.interbank.reserve_requests",
                                     description="허브 예치금 입금·인출 신청 (ClearingHub SPEC 10.9)")
    sub = parser.add_subparsers(dest="command", required=True)
    for kind in ("deposit", "withdraw"):
        p = sub.add_parser(kind, help=f"{'입금' if kind == 'deposit' else '인출'} 신청")
        p.add_argument("amount", type=int)
        p.add_argument("--memo", default="")
    sub.add_parser("list", help="최근 신청 50건")
    sub.add_parser("sync", help="열린 신청을 허브와 맞춘다 (승인이면 장부 반영)")
    c = sub.add_parser("cancel", help="결정 전 신청 취소")
    c.add_argument("request_id", type=int)
    sub.add_parser("reserve", help="허브의 내 예치금 (GET /v1/reserve)")
    args = parser.parse_args(argv)
    if not get_settings().interbank_enabled:
        print("허브 설정(HUB_URL 등)이 없습니다", file=sys.stderr)
        return 1
    try:
        async with SessionLocal() as db:
            if args.command in ("deposit", "withdraw"):
                print(_line(await request(db, args.command.upper(), args.amount, args.memo)))
            elif args.command == "list":
                for req in await list_requests(db):
                    print(_line(req))
            elif args.command == "sync":
                changed = await sync(db)
                print("\n".join(_line(r) for r in changed) or "바뀐 신청 없음")
            elif args.command == "cancel":
                print(_line(await cancel(db, args.request_id)))
            else:
                reply = await hub_client.reserve()
                print(reply.body if reply.ok else f"실패: {reply.status} {reply.error} {reply.message}")
    except ApiException as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    loop_factory = (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) if sys.platform == "win32" else None
    sys.exit(asyncio.run(_cli(sys.argv[1:]), loop_factory=loop_factory))
