from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.clock import now_utc, start_of_today_utc, today_kst
from avengers_bank.core.exceptions import BadRequestException, NotFoundException
from avengers_bank.domains.accounts.models import (
    CheckingAccount,
    CheckingAccountHistory,
    DepositAccount,
    DepositAccountHistory,
    HistoryType,
    SavingsAccount,
    SavingsAccountHistory,
)
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.recipients.repository import recipient_repository
from avengers_bank.domains.transfers.schemas import (
    DepositPaymentCreate,
    SavingsPaymentCreate,
    TransferCreate,
    TransferResponse,
)
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import UserResponse


def check_balance(account: CheckingAccount, amount: int) -> None:
    if account.balance < amount:
        raise BadRequestException(code="INSUFFICIENT_BALANCE", message="잔액이 부족합니다.")


class TransferService:
    # 이 도메인은 테이블이 없다. 계좌 데이터는 accounts.repository를 통해 읽고 쓴다.

    async def transfer(
        self, db: AsyncSession, data: TransferCreate, current_user: UserResponse
    ) -> TransferResponse:
        async with db.begin():
            # 1. 보내는 계좌가 본인 것인지 확인
            source = await account_service.get_owned_account(
                db, "checking", data.from_checking_account_id, current_user.user_id
            )
            # 2. 받는 계좌 찾기
            target = await account_repository.find_checking_by_account_num(db, data.to_account_num)
            if target is None:
                raise NotFoundException(
                    code="ACCOUNT_NOT_FOUND", message="받는 계좌를 찾을 수 없습니다."
                )
            if target.checking_account_id == source.checking_account_id:
                raise BadRequestException(
                    code="SAME_ACCOUNT", message="같은 계좌로는 이체할 수 없습니다."
                )
            locked = await account_repository.lock_checking_accounts(
                db, [source.checking_account_id, target.checking_account_id]
            )
            source, target = locked[source.checking_account_id], locked[target.checking_account_id]

            # 3. 잔액, 1회 한도, 1일 한도 검사
            check_balance(source, data.amount)
            if data.amount > source.per_transfer_limit:
                raise BadRequestException(
                    code="PER_TRANSFER_LIMIT_EXCEEDED", message="1회 이체 한도를 초과했습니다."
                )
            sent_today = await account_repository.sum_transfer_out_since(
                db, source.checking_account_id, start_of_today_utc()
            )
            if sent_today + data.amount > source.daily_transfer_limit:
                raise BadRequestException(
                    code="DAILY_LIMIT_EXCEEDED", message="1일 이체 한도를 초과했습니다."
                )

            # TODO(2단계 FDS): fds_service.evaluate(...) → LOW / MEDIUM / HIGH
            #   HIGH → BadRequestException(code="FDS_BLOCKED") + fds_logs 기록
            #   MEDIUM + PIN 미검증 → BadRequestException(code="ADDITIONAL_AUTH_REQUIRED")

            # 4. 양쪽 balance 변경
            source.balance -= data.amount
            target.balance += data.amount

            # 5. 양쪽 History 한 줄씩 저장
            now = now_utc()
            common = {
                "date": now,
                "from_account": source.account_num,
                "sending_account": target.account_num,
            }
            await account_repository.save(
                db,
                CheckingAccountHistory(
                    checking_account_id=source.checking_account_id,
                    change_amount=-data.amount,
                    type=HistoryType.TRANSFER_OUT,
                    **common,
                ),
            )
            await account_repository.save(
                db,
                CheckingAccountHistory(
                    checking_account_id=target.checking_account_id,
                    change_amount=data.amount,
                    type=HistoryType.TRANSFER_IN,
                    **common,
                ),
            )
            await recipient_repository.touch_last_sent_at(
                db, current_user.user_id, target.account_num, now
            )
            holder = await user_repository.find_by_id(db, target.user_id)

            return TransferResponse(
                from_account_num=source.account_num,
                to_account_num=target.account_num,
                to_holder_name=holder.name if holder else None,
                amount=data.amount,
                balance_after=source.balance,
                transferred_at=now,
            )

    async def pay_savings(
        self, db: AsyncSession, data: SavingsPaymentCreate, current_user: UserResponse
    ) -> TransferResponse:
        async with db.begin():
            source = await account_service.get_owned_account(
                db, "checking", data.from_checking_account_id, current_user.user_id, for_update=True
            )
            savings: SavingsAccount = await account_service.get_owned_account(
                db, "savings", data.savings_account_id, current_user.user_id, for_update=True
            )
            amount = data.amount or savings.monthly_payment
            return await self._move_to_own_account(
                db, source, savings, amount, HistoryType.SAVINGS_PAYMENT,
                SavingsAccountHistory(savings_account_id=savings.savings_account_id),
            )

    async def pay_deposit(
        self, db: AsyncSession, data: DepositPaymentCreate, current_user: UserResponse
    ) -> TransferResponse:
        async with db.begin():
            source = await account_service.get_owned_account(
                db, "checking", data.from_checking_account_id, current_user.user_id, for_update=True
            )
            deposit: DepositAccount = await account_service.get_owned_account(
                db, "deposit", data.deposit_account_id, current_user.user_id, for_update=True
            )
            return await self._move_to_own_account(
                db, source, deposit, data.amount, HistoryType.DEPOSIT_PAYMENT,
                DepositAccountHistory(deposit_account_id=deposit.deposit_account_id),
            )

    async def _move_to_own_account(
        self,
        db: AsyncSession,
        source: CheckingAccount,
        target: SavingsAccount | DepositAccount,
        amount: int,
        source_history_type: HistoryType,
        target_history: SavingsAccountHistory | DepositAccountHistory,
    ) -> TransferResponse:
        """입출금 → 본인 적금·예금. 본인 계좌끼리라 이체 한도는 적용하지 않는다."""
        if target.maturity_date < today_kst():
            raise BadRequestException(
                code="ACCOUNT_MATURED", message="만기가 지난 계좌에는 입금할 수 없습니다."
            )
        check_balance(source, amount)

        source.balance -= amount
        target.balance += amount

        now = now_utc()
        await account_repository.save(
            db,
            CheckingAccountHistory(
                checking_account_id=source.checking_account_id,
                date=now,
                change_amount=-amount,
                type=source_history_type,
                from_account=source.account_num,
                sending_account=target.account_num,
            ),
        )
        target_history.date = now
        target_history.deposit_amount = amount
        target_history.type = HistoryType.DEPOSIT
        target_history.from_account = source.account_num
        await account_repository.save(db, target_history)

        return TransferResponse(
            from_account_num=source.account_num,
            to_account_num=target.account_num,
            amount=amount,
            balance_after=source.balance,
            transferred_at=now,
        )


transfer_service = TransferService()
