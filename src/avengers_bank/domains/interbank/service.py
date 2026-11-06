"""다른 은행 이체의 돈 흐름.

보내기 (SPEC 6절)
  1. 허브로 예금주 확인 (계좌 없음이면 출금 전에 끝)
  2. [트랜잭션] 한도·FDS 통과 → 출금 + interbank_transfers(PENDING)   ← transfers.service가 한다
  3. 허브에 이체 요청
     200 COMPLETED → 완료 / 4xx → 출금 되돌림(TRANSFER_REFUND) / 202·응답 없음 → PENDING 유지
  4. PENDING은 confirm_pending이 허브에 결과를 물어 확정한다. 결과를 모르는 채로는 절대 되돌리지 않는다
     (되돌렸는데 실제로 입금됐다면 돈이 두 배가 된다)

받기 (SPEC 4절): receive가 transfer_id로 한 번만 입금한다.

내부 계정 분개 (interbank_ledger, 고객 잔액 변경과 같은 트랜잭션):
  출금   고객 -a  / 중간 계정 +a
  완료             중간 계정 -a / 정산 계정(받는 은행) +a
  되돌림 고객 +a  / 중간 계정 -a
  받기   고객 +a  / 정산 계정(보낸 은행) -a
  정산   정산 계정(은행별) -n / 예치금 계정 -n   (n = 허브 run에서 그 은행에 줄 돈, 받을 돈이면 음수. settlement_sync)
reconcile이 내부 계정 잔액과 거래 기록이 맞는지 확인한다.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.clock import now_utc, real_now_utc
from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException, BadRequestException, NotFoundException
from avengers_bank.domains.accounts.models import CheckingAccount, CheckingAccountHistory, HistoryType
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.interbank.hub_client import HubReply, hub_client
from avengers_bank.domains.interbank.models import (
    HubAccountQuery,
    InterbankLedgerEntry,
    InterbankReceipt,
    InterbankStatus,
    InterbankTransfer,
    LedgerAccount,
    LedgerEvent,
    OwnAccountLookup,
    OwnAccountRef,
    SettlementReconciliation,
)
from avengers_bank.domains.interbank.signing import HUB_BANK_CODE
from avengers_bank.domains.products.models import AccountProduct
from avengers_bank.domains.users.ci import ci_of
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.repository import user_repository

logger = logging.getLogger(__name__)


class InterbankUnavailable(ApiException):
    def __init__(self, message: str = "다른 은행 이체를 지금 처리할 수 없습니다. 잠시 후 다시 시도해 주세요."):
        super().__init__(status_code=503, code="INTERBANK_UNAVAILABLE", message=message)


def is_external(to_bank: str | None) -> bool:
    return to_bank is not None and to_bank != get_settings().bank_code


def fds_account_key(to_bank: str, to_account: str) -> str:
    """FDS에 넘기는 받는 계좌. 은행 코드를 붙여 우리 은행의 같은 번호 계좌(등록 수취인)와 섞이지 않게 한다."""
    return f"{to_bank}:{to_account}"


def _require_enabled() -> None:
    if not get_settings().interbank_enabled:
        raise InterbankUnavailable("다른 은행 이체가 설정되지 않았습니다.")


async def list_banks() -> list[dict]:
    _require_enabled()
    reply = await hub_client.banks()
    if not reply.ok:
        raise InterbankUnavailable()
    own = get_settings().bank_code
    return [b for b in reply.body.get("banks", []) if b.get("bank_code") != own]


OWN_BANK_ALIASES = ("avengers", "어벤저스", "어벤져스")


def _bank_key(name: str) -> str:
    key = name.lower().replace(" ", "")
    for word in ("은행", "bank", "으로", "로", "에서"):
        key = key.replace(word, "")
    return key


async def find_bank(name: str) -> dict:
    """사용자가 말한 은행 이름("심뱅크", "SimBank", "B은행") → {bank_code, name, own}.
    우리 은행이면 own=True (허브 설정이 없어도 된다). 하나로 정해지지 않으면 BANK_NOT_FOUND와 보낼 수 있는 은행 목록."""
    key = _bank_key(name)
    if key and any(alias in key or key in alias for alias in OWN_BANK_ALIASES):
        return {"bank_code": get_settings().bank_code, "name": "AvengersBank", "own": True}
    banks = await list_banks() if get_settings().interbank_enabled else []
    matched = [b for b in banks if key and (key in _bank_key(b["name"]) or _bank_key(b["name"]) in key or key == b["bank_code"])]
    if len(matched) == 1:
        return {**matched[0], "own": False}
    names = ", ".join(b["name"] for b in banks) or "없음 (다른 은행 이체를 쓸 수 없어요)"
    raise NotFoundException(code="BANK_NOT_FOUND", message=f'"{name}" 은행을 찾지 못했어요. 보낼 수 있는 다른 은행: {names}')


async def bank_name(bank_code: str) -> str:
    for b in await list_banks():
        if b["bank_code"] == bank_code:
            return b["name"]
    raise NotFoundException(code="BANK_NOT_FOUND", message="보낼 수 없는 은행이에요.")


async def inquiry(to_bank: str, to_account: str) -> str:
    """받는 사람 이름. 돈을 움직이기 전에 부른다."""
    _require_enabled()
    reply = await hub_client.inquiry(to_bank, to_account)
    if reply.ok and reply.body.get("holder_name"):
        return str(reply.body["holder_name"])
    if reply.rejected:
        if reply.status == 404:
            raise NotFoundException(code=reply.error, message=reply.message or "받는 계좌를 찾을 수 없습니다.")
        raise BadRequestException(code=reply.error, message=reply.message or "받는 은행이 조회를 거절했습니다.")
    raise InterbankUnavailable()


def _post(db: AsyncSession, transfer_id: str, event: LedgerEvent, bank_code: str,
          *lines: tuple[LedgerAccount, int], hub_run_id: int | None = None) -> None:
    """내부 계정 분개. 호출하는 쪽의 트랜잭션 안에서, 고객 잔액을 바꾸는 것과 함께 부른다.
    예치금 계정(HUB_RESERVE)은 은행별이 아니므로 bank_code 대신 허브 코드("000")로 남긴다."""
    now = now_utc()
    db.add_all(
        InterbankLedgerEntry(transfer_id=transfer_id, account=account, event=event, amount=amount, created_at=now,
                             bank_code=HUB_BANK_CODE if account == LedgerAccount.HUB_RESERVE else bank_code,
                             hub_run_id=hub_run_id)
        for account, amount in lines
    )


async def debit(
    db: AsyncSession, *, user_id: int, source: CheckingAccount, to_bank: str, to_account: str,
    amount: int, holder_name: str | None, to_account_ref: str | None = None,
) -> InterbankTransfer:
    """출금(고객 → 중간 계정) + 송금 기록(PENDING). 호출하는 쪽의 트랜잭션 안에서, 잠근 source로 부른다."""
    now = now_utc()
    source.balance -= amount
    await account_repository.save(db, CheckingAccountHistory(
        checking_account_id=source.checking_account_id, date=now, change_amount=-amount,
        type=HistoryType.TRANSFER_OUT, from_account=source.account_num, sending_account=to_account,
    ))
    transfer = InterbankTransfer(
        transfer_id=str(uuid.uuid4()), user_id=user_id, checking_account_id=source.checking_account_id,
        to_bank=to_bank, to_account=to_account, to_account_ref=to_account_ref, to_holder_name=holder_name,
        amount=amount, status=InterbankStatus.PENDING,
    )
    db.add(transfer)
    _post(db, transfer.transfer_id, LedgerEvent.DEBIT, to_bank, (LedgerAccount.SUSPENSE, amount))
    await db.flush()
    return transfer


async def _payload(db: AsyncSession, transfer: InterbankTransfer) -> dict:
    source = await db.get(CheckingAccount, transfer.checking_account_id)
    user = await user_repository.find_by_id(db, transfer.user_id)
    # 내 다른 은행 계좌로 보낼 때는 실제 계좌번호를 모르므로 허브가 준 참조값을 보낸다 (SPEC 9.3)
    destination = {"to_account_ref": transfer.to_account_ref} if transfer.to_account_ref else {"to_account": transfer.to_account}
    return {
        "transfer_id": transfer.transfer_id, "to_bank": transfer.to_bank, **destination,
        "from_account": source.account_num, "amount": transfer.amount, "sender_name": user.name[:50],
        "memo": transfer.memo,
    }


async def _refund(db: AsyncSession, transfer: InterbankTransfer, code: str, message: str) -> None:
    [source] = (await account_repository.lock_checking_accounts(db, [transfer.checking_account_id])).values()
    source.balance += transfer.amount
    await account_repository.save(db, CheckingAccountHistory(
        checking_account_id=source.checking_account_id, date=now_utc(), change_amount=transfer.amount,
        type=HistoryType.TRANSFER_REFUND, from_account=transfer.to_account[:20], sending_account=source.account_num,
    ))
    _post(db, transfer.transfer_id, LedgerEvent.REFUND, transfer.to_bank, (LedgerAccount.SUSPENSE, -transfer.amount))
    transfer.status = InterbankStatus.FAILED
    transfer.fail_code, transfer.fail_message = code[:40], message[:200]
    transfer.finished_at = now_utc()
    logger.info("타행 이체 %s 실패, 출금 되돌림: %s", transfer.transfer_id, code)


async def _apply(db: AsyncSession, transfer: InterbankTransfer, reply: HubReply) -> None:
    """허브 응답을 반영한다. 이미 확정된 거래는 건드리지 않는다 (worker와 요청이 겹칠 때)."""
    if transfer.status != InterbankStatus.PENDING:
        return
    hub_status = reply.body.get("status")
    if reply.ok and hub_status == "COMPLETED":
        _post(db, transfer.transfer_id, LedgerEvent.COMPLETE, transfer.to_bank,
              (LedgerAccount.SUSPENSE, -transfer.amount), (LedgerAccount.SETTLEMENT, transfer.amount))
        transfer.status = InterbankStatus.COMPLETED
        transfer.to_holder_name = reply.body.get("holder_name") or transfer.to_holder_name
        transfer.finished_at = now_utc()
    elif reply.rejected or (reply.ok and hub_status == "FAILED"):
        code = reply.error if reply.rejected else str(reply.body.get("fail_code") or "FAILED")
        message = reply.message if reply.rejected else str(reply.body.get("fail_message") or "")
        await _refund(db, transfer, code, message or "받는 은행이 이체를 거절했습니다.")
    # 그 밖(202 PENDING, 5xx, 응답 없음, 허브의 UNKNOWN): 결과를 모르므로 그대로 둔다


async def _locked(db: AsyncSession, transfer_id: str) -> InterbankTransfer:
    return await db.scalar(
        select(InterbankTransfer).where(InterbankTransfer.transfer_id == transfer_id).with_for_update()
    )


async def deliver(db: AsyncSession, transfer_id: str) -> InterbankTransfer:
    """출금을 커밋한 뒤 허브에 이체를 요청하고 결과를 반영한다."""
    async with db.begin():
        payload = await _payload(db, await db.get(InterbankTransfer, transfer_id))
    reply = await hub_client.transfer(payload)
    async with db.begin():
        transfer = await _locked(db, transfer_id)
        await _apply(db, transfer, reply)
    return transfer


async def confirm_pending(db: AsyncSession) -> int:
    """PENDING 타행 이체를 허브에 물어 확정한다 (worker가 주기적으로 부른다). 확정된 건수를 돌려준다.
    허브가 그 거래를 모르면(404) 요청이 허브에 닿지 않은 것이므로 같은 transfer_id로 다시 보낸다 (멱등)."""
    async with db.begin():
        ids = list(await db.scalars(
            select(InterbankTransfer.transfer_id).where(InterbankTransfer.status == InterbankStatus.PENDING)
        ))
    confirmed = 0
    for transfer_id in ids:
        reply = await hub_client.get_transfer(transfer_id)
        if reply.status == 404:
            async with db.begin():
                payload = await _payload(db, await db.get(InterbankTransfer, transfer_id))
            reply = await hub_client.transfer(payload)
        elif reply.rejected:  # 401·403 등 조회 자체가 거절됨: 설정 문제. 결과는 모르므로 되돌리지 않는다
            logger.error("타행 이체 %s 조회 거절: %s %s", transfer_id, reply.error, reply.message)
            reply = HubReply(None, {})
        async with db.begin():
            transfer = await _locked(db, transfer_id)
            await _apply(db, transfer, reply)
            if transfer.status == InterbankStatus.PENDING:
                transfer.check_count += 1
            else:
                confirmed += 1
    return confirmed


# ── 내부 계정 잔액·대사 ────────────────────────────────────────────

async def ledger_balances(db: AsyncSession) -> dict[str, int]:
    """내부 계정 잔액. {"INTERBANK_SUSPENSE": n, "INTERBANK_SETTLEMENT:902": n, "HUB_RESERVE": n, ...}"""
    rows = await db.execute(
        select(InterbankLedgerEntry.account, InterbankLedgerEntry.bank_code, func.sum(InterbankLedgerEntry.amount))
        .group_by(InterbankLedgerEntry.account, InterbankLedgerEntry.bank_code)
    )
    balances: dict[str, int] = {LedgerAccount.SUSPENSE.value: 0}
    for account, bank_code, total in rows:
        key = account if account in (LedgerAccount.SUSPENSE, LedgerAccount.HUB_RESERVE) else f"{account}:{bank_code}"
        balances[key] = balances.get(key, 0) + int(total or 0)
    return balances


async def reconcile(db: AsyncSession) -> list[str]:
    """내부 계정 잔액이 거래 기록과 맞는지 확인한다. 어긋난 내용 목록 (비어 있으면 정상).
      중간 계정 = PENDING 이체 금액 합
      은행별 정산 계정 = 그 은행으로 완료된 이체 합 - 그 은행에서 받은 입금 합 + 그 은행 SETTLE 분개의 정산 계정 줄 합
      예치금 계정 = 장부를 정리한 허브 run의 net_amount 합 (settlement_reconciliations.settled_at이 있는 행)
      그리고 은행마다, 허브 run에 묶인 정산 계정 줄(맞춘 COMPLETE·RECEIVE와 SETTLE)의 합 = 0
      (정리한 run의 몫이 정산 계정에 남거나 모자라지 않았는지)"""
    entry = InterbankLedgerEntry
    async with db.begin():
        balances = await ledger_balances(db)
        pending = await db.scalar(
            select(func.coalesce(func.sum(InterbankTransfer.amount), 0)).where(InterbankTransfer.status == InterbankStatus.PENDING)
        )
        expected: dict[str, int] = {LedgerAccount.SUSPENSE.value: int(pending)}
        sent = await db.execute(
            select(InterbankTransfer.to_bank, func.sum(InterbankTransfer.amount))
            .where(InterbankTransfer.status == InterbankStatus.COMPLETED).group_by(InterbankTransfer.to_bank)
        )
        received = await db.execute(
            select(InterbankReceipt.from_bank, func.sum(InterbankReceipt.amount)).group_by(InterbankReceipt.from_bank)
        )
        for bank, total in sent:
            key = f"{LedgerAccount.SETTLEMENT}:{bank}"
            expected[key] = expected.get(key, 0) + int(total)
        for bank, total in received:
            key = f"{LedgerAccount.SETTLEMENT}:{bank}"
            expected[key] = expected.get(key, 0) - int(total)
        settled = await db.execute(
            select(entry.bank_code, func.sum(entry.amount))
            .where(entry.event == LedgerEvent.SETTLE, entry.account == LedgerAccount.SETTLEMENT)
            .group_by(entry.bank_code)
        )
        for bank, total in settled:
            key = f"{LedgerAccount.SETTLEMENT}:{bank}"
            expected[key] = expected.get(key, 0) + int(total)
        reserve = await db.scalar(
            select(func.coalesce(func.sum(SettlementReconciliation.hub_net_amount), 0))
            .where(SettlementReconciliation.settled_at.is_not(None))
        )
        expected[LedgerAccount.HUB_RESERVE.value] = int(reserve)
        leftovers = await db.execute(
            select(entry.bank_code, func.sum(entry.amount))
            .where(entry.account == LedgerAccount.SETTLEMENT, entry.hub_run_id.is_not(None))
            .group_by(entry.bank_code).having(func.sum(entry.amount) != 0)
        )
        problems = [f"{LedgerAccount.SETTLEMENT}:{bank}: 정리한 허브 run의 몫이 {int(total):,} 남음 (0이어야 함)"
                    for bank, total in leftovers]
    return [
        f"{key}: 분개 잔액 {balances.get(key, 0):,} ≠ 거래 기록 {expected.get(key, 0):,}"
        for key in sorted(balances.keys() | expected.keys())
        if balances.get(key, 0) != expected.get(key, 0)
    ] + problems


async def settlement_positions(db: AsyncSession, start: datetime, end: datetime) -> list[dict]:
    """기간 [start, end) 동안 은행별 정산 계정 움직임: 보낸 금액, 받은 금액, 순액(+면 우리가 줄 돈).
    허브 정산표(은행 쌍별 양방향 합계·순 금액)와 맞춰 볼 때 쓴다. 시각은 우리가 확정을 기록한 때다."""
    entry = InterbankLedgerEntry
    async with db.begin():
        rows = await db.execute(
            select(entry.bank_code,
                   func.coalesce(func.sum(entry.amount).filter(entry.amount > 0), 0),
                   func.coalesce(func.sum(-entry.amount).filter(entry.amount < 0), 0))
            .where(entry.account == LedgerAccount.SETTLEMENT, entry.event.in_((LedgerEvent.COMPLETE, LedgerEvent.RECEIVE)),
                   entry.created_at >= start, entry.created_at < end)
            .group_by(entry.bank_code).order_by(entry.bank_code)
        )
        return [{"bank_code": bank, "sent": int(out), "received": int(inc), "net": int(out) - int(inc)}
                for bank, out, inc in rows]


async def list_my_transfers(db: AsyncSession, user_id: int, limit: int = 50) -> list[InterbankTransfer]:
    stmt = (select(InterbankTransfer).where(InterbankTransfer.user_id == user_id)
            .order_by(InterbankTransfer.created_at.desc()).limit(limit))
    return list(await db.scalars(stmt))


# ── 받기 (허브 → 우리) ─────────────────────────────────────────────

async def holder_name_of(db: AsyncSession, account_num: str) -> str | None:
    async with db.begin():
        account = await account_repository.find_checking_by_account_num(db, account_num)
        if account is None:
            return None
        user = await user_repository.find_by_id(db, account.user_id)
        return user.name if user else None


async def receive(db: AsyncSession, data: dict) -> tuple[int, dict]:
    """다른 은행에서 온 입금. 같은 transfer_id는 한 번만 입금하고 같은 응답을 준다. (HTTP 상태, 본문)."""
    transfer_id = data["transfer_id"]
    try:
        async with db.begin():
            if await db.get(InterbankReceipt, transfer_id) is not None:
                return 200, await _receipt_body(db, transfer_id)
            account = await account_repository.find_checking_by_account_num(db, data["to_account"], for_update=True)
            if account is None:
                return 404, {"error": "ACCOUNT_NOT_FOUND", "message": "받는 계좌를 찾을 수 없습니다", "transfer_id": transfer_id}
            now = now_utc()
            account.balance += data["amount"]
            db.add(InterbankReceipt(
                transfer_id=transfer_id, checking_account_id=account.checking_account_id,
                from_bank=data["from_bank"], from_bank_name=data.get("from_bank_name", "")[:50],
                from_account=data["from_account"], sender_name=data["sender_name"], amount=data["amount"],
                memo=data.get("memo", ""), received_at=now,
            ))
            _post(db, transfer_id, LedgerEvent.RECEIVE, data["from_bank"], (LedgerAccount.SETTLEMENT, -data["amount"]))
            await account_repository.save(db, CheckingAccountHistory(
                checking_account_id=account.checking_account_id, date=now, change_amount=data["amount"],
                type=HistoryType.TRANSFER_IN, from_account=data["from_account"][:20], sending_account=account.account_num,
            ))
    except IntegrityError:  # 같은 transfer_id가 동시에 두 번 와서 한쪽이 먼저 저장함 → 그쪽 결과를 준다
        await db.rollback()
    async with db.begin():
        return 200, await _receipt_body(db, transfer_id)


async def _receipt_body(db: AsyncSession, transfer_id: str) -> dict:
    receipt = await db.get(InterbankReceipt, transfer_id)
    account = await db.get(CheckingAccount, receipt.checking_account_id)
    user = await user_repository.find_by_id(db, account.user_id)
    return {"transfer_id": transfer_id, "status": "COMPLETED", "holder_name": user.name if user else ""}


async def receipt_status(db: AsyncSession, transfer_id: str) -> dict | None:
    async with db.begin():
        receipt = await db.get(InterbankReceipt, transfer_id)
        if receipt is None:
            return None
        account = await db.get(CheckingAccount, receipt.checking_account_id)
        user = await user_repository.find_by_id(db, account.user_id)
        return {"transfer_id": transfer_id, "status": "COMPLETED", "holder_name": user.name if user else "",
                "received_at": receipt.received_at.isoformat(timespec="seconds")}


# ── 다른 은행 내 계좌 (SPEC 9절) ───────────────────────────────────

REF_TTL = timedelta(minutes=29)  # 허브는 30분. 경계에서 만료가 엇갈리지 않게 조금 짧게 둔다


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def lookup_own_accounts(db: AsyncSession, user_id: int) -> tuple[list[OwnAccountRef], list[dict]]:
    """동의를 기록하고 허브에 내 CI로 다른 은행 계좌를 묻는다. (계좌 목록, 은행별 결과)."""
    _require_enabled()
    if get_settings().ci_key is None:
        raise InterbankUnavailable("다른 은행 내 계좌 불러오기가 설정되지 않았습니다.")
    async with db.begin():
        user = await user_repository.find_by_id(db, user_id)
        if not user.birth_date:
            raise BadRequestException(code="BIRTH_DATE_REQUIRED", message="생년월일을 등록해야 다른 은행 내 계좌를 불러올 수 있어요.")
        user.ci = ci_of(user.name, user.birth_date, user.phone)  # 키를 나중에 넣은 사용자도 여기서 채운다
        ci = user.ci
        consent_id = "avb-" + str(uuid.uuid4())
        db.add(OwnAccountLookup(consent_id=consent_id, user_id=user_id, consented_at=real_now_utc()))

    reply = await hub_client.lookup_accounts(ci, consent_id)
    if reply.status == 429:
        raise ApiException(status_code=429, code="TOO_MANY_LOOKUPS", message="오늘은 더 불러올 수 없어요. 내일 다시 시도해 주세요.")
    if not reply.ok:
        raise InterbankUnavailable()

    expires_at = real_now_utc() + REF_TTL
    refs = [
        OwnAccountRef(ref=str(a["account_ref"]), user_id=user_id, consent_id=consent_id, bank_code=str(a["bank_code"]),
                      bank_name=str(a.get("bank_name") or a["bank_code"])[:50], account_masked=str(a["account_masked"])[:50],
                      product_name=str(a.get("product_name") or "")[:50], expires_at=expires_at)
        for a in reply.body.get("accounts", []) if isinstance(a, dict) and a.get("account_ref")
    ]
    async with db.begin():
        lookup = await db.get(OwnAccountLookup, consent_id)
        lookup.hub_lookup_id, lookup.account_count = reply.body.get("lookup_id"), len(refs)
        await db.execute(delete(OwnAccountRef).where(OwnAccountRef.user_id == user_id, OwnAccountRef.expires_at < real_now_utc()))
        db.add_all(refs)
    return refs, [b for b in reply.body.get("banks", []) if isinstance(b, dict)]


async def resolve_own_ref(db: AsyncSession, user_id: int, ref: str, to_bank: str) -> OwnAccountRef:
    """이체에 쓸 참조값이 이 사용자 것이고, 받는 은행이 맞고, 만료 전인지. 호출하는 쪽의 트랜잭션 안에서 부른다."""
    row = await db.get(OwnAccountRef, ref)
    if row is None or row.user_id != user_id or row.bank_code != to_bank or _as_utc(row.expires_at) <= real_now_utc():
        raise BadRequestException(code="ACCOUNT_REF_INVALID", message="계좌 정보가 만료됐어요. 다른 은행 내 계좌를 다시 불러와 주세요.")
    return row


async def own_accounts_by_ci(db: AsyncSession, ci: str) -> list[dict]:
    """허브 → 우리: 이 CI를 가진 고객의 입출금 계좌 (SPEC 9.4). 고객이 없으면 빈 목록.
    조회 기록(시각, ci, 돌려준 계좌 수)을 같은 트랜잭션에 남긴다 (9.4 규칙 5)."""
    async with db.begin():
        accounts: list[dict] = []
        users = list(await db.scalars(select(User).where(User.ci == ci)))
        if users:
            rows = await db.execute(
                select(CheckingAccount.account_num, AccountProduct.name)
                .join(AccountProduct, AccountProduct.product_id == CheckingAccount.product_id)
                .where(CheckingAccount.user_id.in_([u.user_id for u in users]))
                .order_by(CheckingAccount.created_at)
            )
            accounts = [{"account_num": num, "product_name": (name or "")[:50]} for num, name in rows]
        db.add(HubAccountQuery(ci=ci, account_count=len(accounts), queried_at=real_now_utc()))
        return accounts
