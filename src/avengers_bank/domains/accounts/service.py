import calendar
import secrets
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.clock import today_kst
from avengers_bank.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from avengers_bank.domains.accounts.models import (
    CheckingAccount,
    CheckingAccountHistory,
    DepositAccount,
    SavingsAccount,
)
from avengers_bank.domains.accounts.repository import (
    Account,
    AccountHistory,
    account_id_of,
    account_repository,
)
from avengers_bank.domains.accounts.schemas import (
    AccountDetailResponse,
    AccountHistoryResponse,
    AccountSummaryResponse,
    AccountType,
    AccountUpdate,
    CheckingAccountCreate,
    DepositAccountCreate,
    SavingsAccountCreate,
)
from avengers_bank.domains.products.service import product_service
from avengers_bank.domains.users.schemas import UserResponse

# 계좌번호 형식: 110-XXX-XXXXXX (입출금), 220-… (예금), 330-… (적금)
ACCOUNT_NUM_PREFIX = {"checking": "110", "deposit": "220", "savings": "330"}
MAX_ISSUE_ATTEMPTS = 10


def add_months(start: date, months: int) -> date:
    """1월 31일 + 1개월 = 2월 28(29)일처럼 말일을 넘지 않게 더한다."""
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def to_summary(account_type: str, account: Account) -> AccountSummaryResponse:
    return AccountSummaryResponse(
        account_type=account_type,
        account_id=account_id_of(account_type, account),
        account_num=account.account_num,
        balance=account.balance,
        nickname=account.nickname,
        created_at=account.created_at,
    )


def to_detail(account_type: str, account: Account) -> AccountDetailResponse:
    return AccountDetailResponse(
        **to_summary(account_type, account).model_dump(),
        product_id=account.product_id,
        per_transfer_limit=getattr(account, "per_transfer_limit", None),
        daily_transfer_limit=getattr(account, "daily_transfer_limit", None),
        maturity_date=getattr(account, "maturity_date", None),
        monthly_payment=getattr(account, "monthly_payment", None),
        monthly_deposit_date=getattr(account, "monthly_deposit_date", None),
    )


def to_history(account_type: str, history: AccountHistory) -> AccountHistoryResponse:
    return AccountHistoryResponse(
        history_id=getattr(history, f"{account_type}_account_history_id"),
        date=history.date,
        amount=(
            history.change_amount
            if isinstance(history, CheckingAccountHistory)
            else history.deposit_amount
        ),
        type=history.type,
        from_account=history.from_account,
        sending_account=getattr(history, "sending_account", None),
    )


class AccountService:
    async def open_checking(
        self, db: AsyncSession, data: CheckingAccountCreate, current_user: UserResponse
    ) -> AccountDetailResponse:
        async with db.begin():
            await product_service.validate_account_product(db, data.product_id, "CHECKING")
            account = CheckingAccount(
                user_id=current_user.user_id,
                product_id=data.product_id,
                account_num=await self._issue_account_num(db, "checking"),
                balance=0,
                per_transfer_limit=data.per_transfer_limit,
                daily_transfer_limit=data.daily_transfer_limit,
                nickname=data.nickname,
            )
            await self._save_new(db, account)
            return to_detail("checking", account)

    async def open_deposit(
        self, db: AsyncSession, data: DepositAccountCreate, current_user: UserResponse
    ) -> AccountDetailResponse:
        async with db.begin():
            await product_service.validate_account_product(db, data.product_id, "DEPOSIT")
            account = DepositAccount(
                user_id=current_user.user_id,
                product_id=data.product_id,
                account_num=await self._issue_account_num(db, "deposit"),
                balance=0,
                maturity_date=add_months(today_kst(), data.term_months),
                nickname=data.nickname,
            )
            await self._save_new(db, account)
            return to_detail("deposit", account)

    async def open_savings(
        self, db: AsyncSession, data: SavingsAccountCreate, current_user: UserResponse
    ) -> AccountDetailResponse:
        async with db.begin():
            await product_service.validate_account_product(db, data.product_id, "SAVINGS")
            account = SavingsAccount(
                user_id=current_user.user_id,
                product_id=data.product_id,
                account_num=await self._issue_account_num(db, "savings"),
                balance=0,
                monthly_payment=data.monthly_payment,
                monthly_deposit_date=data.monthly_deposit_date,
                maturity_date=add_months(today_kst(), data.term_months),
                nickname=data.nickname,
            )
            await self._save_new(db, account)
            return to_detail("savings", account)

    async def get_my_accounts(
        self, db: AsyncSession, current_user: UserResponse
    ) -> list[AccountSummaryResponse]:
        async with db.begin():
            accounts = await account_repository.find_all_by_user_id(db, current_user.user_id)
            return [to_summary(account_type, account) for account_type, account in accounts]

    async def get_account(
        self, db: AsyncSession, account_type: AccountType, account_id: int, current_user: UserResponse
    ) -> AccountDetailResponse:
        async with db.begin():
            account = await self.get_owned_account(db, account_type, account_id, current_user.user_id)
            return to_detail(account_type, account)

    async def get_histories(
        self, db: AsyncSession, account_type: AccountType, account_id: int, current_user: UserResponse
    ) -> list[AccountHistoryResponse]:
        async with db.begin():
            await self.get_owned_account(db, account_type, account_id, current_user.user_id)
            histories = await account_repository.find_histories(db, account_type, account_id)
            return [to_history(account_type, history) for history in histories]

    async def update_account(
        self,
        db: AsyncSession,
        account_type: AccountType,
        account_id: int,
        data: AccountUpdate,
        current_user: UserResponse,
    ) -> AccountDetailResponse:
        changes = data.model_dump(exclude_unset=True)
        async with db.begin():
            account = await self.get_owned_account(db, account_type, account_id, current_user.user_id)

            limit_fields = {"per_transfer_limit", "daily_transfer_limit"} & changes.keys()
            if limit_fields and account_type != "checking":
                raise BadRequestException(
                    code="TRANSFER_LIMIT_NOT_SUPPORTED",
                    message="이체 한도는 입출금 계좌에서만 바꿀 수 있습니다.",
                )
            for field in limit_fields:
                if changes[field] is None:
                    raise BadRequestException(
                        code="INVALID_TRANSFER_LIMIT", message="이체 한도는 비울 수 없습니다."
                    )

            for field, value in changes.items():
                setattr(account, field, value)

            if account_type == "checking" and account.per_transfer_limit > account.daily_transfer_limit:
                raise BadRequestException(
                    code="INVALID_TRANSFER_LIMIT",
                    message="1회 이체 한도는 1일 이체 한도보다 클 수 없습니다.",
                )
            await db.flush()
            return to_detail(account_type, account)

    # ---- 다른 도메인(transfers, cards, recipients)이 열어 둔 트랜잭션 안에서 쓰는 메서드 ----

    async def get_owned_account(
        self,
        db: AsyncSession,
        account_type: AccountType,
        account_id: int,
        user_id: int,
        *,
        for_update: bool = False,
    ) -> Account:
        account = await account_repository.find_by_id(
            db, account_type, account_id, for_update=for_update
        )
        if account is None:
            raise NotFoundException(code="ACCOUNT_NOT_FOUND", message="계좌를 찾을 수 없습니다.")
        if account.user_id != user_id:
            raise ForbiddenException(code="ACCOUNT_FORBIDDEN", message="본인 계좌가 아닙니다.")
        return account

    async def _issue_account_num(self, db: AsyncSession, account_type: str) -> str:
        """계좌번호는 여기서만 발급한다. 3개 테이블을 모두 검사해서 겹치지 않게 한다."""
        prefix = ACCOUNT_NUM_PREFIX[account_type]
        for _ in range(MAX_ISSUE_ATTEMPTS):
            account_num = f"{prefix}-{secrets.randbelow(1000):03d}-{secrets.randbelow(1_000_000):06d}"
            if not await account_repository.exists_by_account_num(db, account_num):
                return account_num
        raise ConflictException(
            code="ACCOUNT_NUM_ISSUE_FAILED", message="계좌번호 발급에 실패했습니다. 다시 시도해 주세요."
        )

    async def _save_new(self, db: AsyncSession, account: Account) -> None:
        await account_repository.save(db, account)
        await db.refresh(account)  # server_default인 created_at 읽기


account_service = AccountService()
