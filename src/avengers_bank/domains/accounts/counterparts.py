"""이체 거래내역의 상대방 (이름·계좌·은행).

거래내역 행에는 양쪽 계좌번호만 있다. 이름은 조회할 때 붙인다 (컬럼을 늘리지 않아 예전 기록에도 이름이 나온다).
  우리 은행 계좌   → 그 계좌 주인 이름 (users.name)
  타행으로 보냄    → interbank_transfers.to_holder_name (보낼 때 허브로 확인한 이름)
  타행에서 받음    → interbank_receipts.sender_name
다른 은행 계좌번호가 우리 계좌번호와 모양이 같을 수 있어서, 타행 기록이 있는 쪽을 먼저 본다.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.accounts.models import CheckingAccount, CheckingAccountHistory, HistoryType
from avengers_bank.domains.interbank.models import InterbankReceipt, InterbankTransfer
from avengers_bank.domains.users.models import User

TRANSFER_TYPES = (HistoryType.TRANSFER_IN, HistoryType.TRANSFER_OUT, HistoryType.TRANSFER_REFUND)


@dataclass(frozen=True)
class Counterpart:
    account: str
    name: str | None = None
    bank: str | None = None  # 다른 은행 코드. None이면 우리 은행
    bank_name: str | None = None  # 알면 (받은 이체는 허브가 알려 준 이름)
    own_ref: bool = False  # 다른 은행 '내 계좌'로 보낸 것 (가린 번호라 다시 보낼 때는 참조값이 필요)


def counterpart_account(history: CheckingAccountHistory) -> str | None:
    """상대 계좌번호. 보냄은 받은 계좌, 받음·되돌림은 보낸 쪽 계좌."""
    if history.type == HistoryType.TRANSFER_OUT:
        return history.sending_account
    if history.type in (HistoryType.TRANSFER_IN, HistoryType.TRANSFER_REFUND):
        return history.from_account
    return None


async def resolve(db: AsyncSession, histories: list[CheckingAccountHistory]) -> dict[int, Counterpart]:
    """이체 행마다 상대방. {checking_account_history_id: Counterpart}"""
    rows = [(h, counterpart_account(h)) for h in histories if h.type in TRANSFER_TYPES]
    rows = [(h, num) for h, num in rows if num]
    if not rows:
        return {}
    nums = {num for _, num in rows}
    account_ids = {h.checking_account_id for h, _ in rows}

    local = dict(
        (await db.execute(
            select(CheckingAccount.account_num, User.name)
            .join(User, User.user_id == CheckingAccount.user_id)
            .where(CheckingAccount.account_num.in_(nums))
        )).all()
    )
    # 히스토리에는 앞 20자만 들어가므로 그 길이로 맞춘다. 같은 계좌로 여러 번 보냈으면 마지막 기록의 이름
    sent: dict[tuple[int, str], InterbankTransfer] = {}
    for t in await db.scalars(
        select(InterbankTransfer)
        .where(InterbankTransfer.checking_account_id.in_(account_ids))
        .order_by(InterbankTransfer.created_at)
    ):
        if t.to_account[:20] in nums:
            sent[(t.checking_account_id, t.to_account[:20])] = t
    received: dict[tuple[int, str], InterbankReceipt] = {}
    for r in await db.scalars(
        select(InterbankReceipt)
        .where(InterbankReceipt.checking_account_id.in_(account_ids))
        .order_by(InterbankReceipt.received_at)
    ):
        if r.from_account[:20] in nums:
            received[(r.checking_account_id, r.from_account[:20])] = r

    result: dict[int, Counterpart] = {}
    for h, num in rows:
        key = (h.checking_account_id, num)
        if h.type == HistoryType.TRANSFER_IN and key in received:
            r = received[key]
            cp = Counterpart(num, r.sender_name, r.from_bank, r.from_bank_name or None)
        elif h.type != HistoryType.TRANSFER_IN and key in sent:
            t = sent[key]
            cp = Counterpart(num, t.to_holder_name, t.to_bank, own_ref=t.to_account_ref is not None)
        else:
            cp = Counterpart(num, local.get(num))
        result[h.checking_account_history_id] = cp
    return result


@dataclass(frozen=True)
class RecentRecipient:
    counterpart: Counterpart
    last_sent_at: datetime


# 최근 보낸 상대를 찾을 때 훑어보는 보냄 기록 수. 한 사람에게 여러 번 보냈어도 이 안에서 대개 충분히 모인다
SCAN_LIMIT = 300


async def recent_recipients(db: AsyncSession, user_id: int, limit: int = 10) -> list[RecentRecipient]:
    """내 입출금 계좌들에서 최근 이체로 보낸 상대 (은행·계좌별 한 번, 최근 순).
    다른 은행 '내 계좌'로 보낸 것은 번호가 가려져 있어 다시 고를 수 없으므로 뺀다."""
    histories = list(await db.scalars(
        select(CheckingAccountHistory)
        .join(CheckingAccount)
        .where(CheckingAccount.user_id == user_id, CheckingAccountHistory.type == HistoryType.TRANSFER_OUT)
        .order_by(CheckingAccountHistory.date.desc(), CheckingAccountHistory.checking_account_history_id.desc())
        .limit(SCAN_LIMIT)
    ))
    found = await resolve(db, histories)
    seen: set[tuple[str | None, str]] = set()
    result: list[RecentRecipient] = []
    for h in histories:
        cp = found.get(h.checking_account_history_id)
        if cp is None or cp.own_ref or (cp.bank, cp.account) in seen:
            continue
        seen.add((cp.bank, cp.account))
        result.append(RecentRecipient(cp, h.date))
        if len(result) == limit:
            break
    return result
