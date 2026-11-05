from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.accounts.models import (
    CheckingAccount,
    CheckingAccountHistory,
    DepositAccount,
    DepositAccountHistory,
    HistoryType,
    SavingsAccount,
    SavingsAccountHistory,
)

type Account = CheckingAccount | DepositAccount | SavingsAccount
type AccountHistory = CheckingAccountHistory | DepositAccountHistory | SavingsAccountHistory

ACCOUNT_MODELS: dict[str, type[Account]] = {
    "checking": CheckingAccount,
    "deposit": DepositAccount,
    "savings": SavingsAccount,
}
HISTORY_MODELS: dict[str, type[AccountHistory]] = {
    "checking": CheckingAccountHistory,
    "deposit": DepositAccountHistory,
    "savings": SavingsAccountHistory,
}


def account_id_of(account_type: str, obj: Account | AccountHistory) -> int:
    """계좌·거래내역 객체에서 계좌 PK를 꺼낸다 (테이블마다 컬럼 이름이 다름)."""
    return getattr(obj, f"{account_type}_account_id")


class AccountRepository:
    async def save(self, db: AsyncSession, obj: Account | AccountHistory) -> None:
        db.add(obj)
        await db.flush()

    async def find_by_id(
        self, db: AsyncSession, account_type: str, account_id: int, *, for_update: bool = False
    ) -> Account | None:
        """for_update=True면 잔액을 바꾸기 전에 행 잠금을 건다 (PostgreSQL SELECT ... FOR UPDATE)."""
        return await db.get(ACCOUNT_MODELS[account_type], account_id, with_for_update=for_update)

    async def find_all_by_user_id(
        self, db: AsyncSession, user_id: int
    ) -> list[tuple[str, Account]]:
        accounts = []
        for account_type, model in ACCOUNT_MODELS.items():
            rows = await db.scalars(select(model).where(model.user_id == user_id))
            accounts += [(account_type, row) for row in rows]
        return sorted(accounts, key=lambda item: (item[1].created_at, item[0]))

    async def find_checking_by_account_num(
        self, db: AsyncSession, account_num: str, *, for_update: bool = False
    ) -> CheckingAccount | None:
        stmt = select(CheckingAccount).where(CheckingAccount.account_num == account_num)
        if for_update:
            stmt = stmt.with_for_update()
        return await db.scalar(stmt)

    async def lock_checking_accounts(
        self, db: AsyncSession, checking_account_ids: list[int]
    ) -> dict[int, CheckingAccount]:
        """여러 입출금 계좌를 id 순서로 잠근다. 순서를 고정해야 A→B, B→A 동시 이체가 교착되지 않는다."""
        stmt = (
            select(CheckingAccount)
            .where(CheckingAccount.checking_account_id.in_(checking_account_ids))
            .order_by(CheckingAccount.checking_account_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return {account.checking_account_id: account for account in await db.scalars(stmt)}

    async def exists_by_account_num(self, db: AsyncSession, account_num: str) -> bool:
        for model in ACCOUNT_MODELS.values():
            if await db.scalar(select(model.account_num).where(model.account_num == account_num)):
                return True
        return False

    async def find_histories(
        self, db: AsyncSession, account_type: str, account_id: int
    ) -> list[AccountHistory]:
        model = HISTORY_MODELS[account_type]
        account_id_column = getattr(model, f"{account_type}_account_id")
        primary_key = getattr(model, f"{account_type}_account_history_id")
        stmt = (
            select(model)
            .where(account_id_column == account_id)
            .order_by(model.date.desc(), primary_key.desc())
        )
        return list(await db.scalars(stmt))

    async def find_user_transfer_outs_since(
        self, db: AsyncSession, user_id: int, since: datetime
    ) -> list[tuple[datetime, int, str | None]]:
        """사용자의 모든 입출금 계좌에서 since 이후 TRANSFER_OUT (시각, 금액(양수), 받은 계좌). FDS 피처용."""
        rows = await db.execute(
            select(
                CheckingAccountHistory.date,
                -CheckingAccountHistory.change_amount,
                CheckingAccountHistory.sending_account,
            )
            .join(CheckingAccount)
            .where(
                CheckingAccount.user_id == user_id,
                CheckingAccountHistory.type == HistoryType.TRANSFER_OUT,
                CheckingAccountHistory.date >= since,
            )
            .order_by(CheckingAccountHistory.date)
        )
        return [tuple(row) for row in rows]

    async def sum_transfer_out_since(
        self, db: AsyncSession, checking_account_id: int, since: datetime
    ) -> int:
        """since 이후 이체로 나간 돈 합계 (양수). 1일 이체 한도 검사용.
        거절돼 되돌려 받은 타행 이체(TRANSFER_REFUND, +)는 빼서 한도를 다시 쓸 수 있게 한다."""
        total = await db.scalar(
            select(func.coalesce(func.sum(-CheckingAccountHistory.change_amount), 0)).where(
                CheckingAccountHistory.checking_account_id == checking_account_id,
                CheckingAccountHistory.type.in_([HistoryType.TRANSFER_OUT, HistoryType.TRANSFER_REFUND]),
                CheckingAccountHistory.date >= since,
            )
        )
        return int(total)


account_repository = AccountRepository()
