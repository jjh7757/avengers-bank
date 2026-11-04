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
from avengers_bank.domains.chat.confirmation import decode_confirmation_token
from avengers_bank.domains.chat.models import ChatSession
from avengers_bank.domains.chat.repository import chat_repository
from avengers_bank.domains.fds.models import FdsDecision
from avengers_bank.domains.fds.rules import RiskLevel
from avengers_bank.domains.fds.service import FdsResult, fds_service
from avengers_bank.domains.recipients.repository import recipient_repository
from avengers_bank.domains.transfers.schemas import (
    DepositPaymentCreate,
    SavingsPaymentCreate,
    TransferCreate,
    TransferResponse,
)
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import UserResponse
from avengers_bank.domains.users.service import user_service

REJECTED = {FdsDecision.BLOCKED, FdsDecision.AUTH_REQUIRED, FdsDecision.AUTH_FAILED}
REJECTION_ERRORS = {
    FdsDecision.BLOCKED: {"code": "FDS_BLOCKED", "message": "이상거래가 의심되어 이체를 차단했습니다."},
    FdsDecision.AUTH_REQUIRED: {
        "code": "ADDITIONAL_AUTH_REQUIRED",
        "message": "평소와 다른 이체입니다. 이체 PIN을 입력해 주세요.",
    },
    FdsDecision.AUTH_FAILED: {"code": "INVALID_PIN", "message": "이체 PIN이 올바르지 않습니다."},
}


def check_balance(account: CheckingAccount, amount: int) -> None:
    if account.balance < amount:
        raise BadRequestException(code="INSUFFICIENT_BALANCE", message="잔액이 부족합니다.")


class TransferService:
    # 이 도메인은 테이블이 없다. 계좌 데이터는 accounts.repository를 통해 읽고 쓴다.

    async def transfer(
        self,
        db: AsyncSession,
        data: TransferCreate,
        current_user: UserResponse,
        client_ip: str | None = None,
    ) -> TransferResponse:
        rejection: FdsDecision | None = None
        async with db.begin():
            # 0. 채팅에서 온 이체면 확인 카드 승인 토큰 검사
            chat_session = await self._check_confirmation(db, data, current_user.user_id)

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

            # 4. FDS 판정 → LOW 통과 / MEDIUM 추가 인증(PIN) / HIGH 차단
            user = await user_repository.find_by_id(db, current_user.user_id)
            fds = await fds_service.evaluate(
                db,
                user=user,
                source=source,
                to_account_num=target.account_num,
                amount=data.amount,
                sent_today=sent_today,
                session_id=data.session_id,
                device_fingerprint=data.device_fingerprint,
                input_mode=data.input_mode,
                session_texts=(
                    await chat_repository.find_user_texts(db, chat_session.session_id) if chat_session else []
                ),
            )
            decision = await self._decide(fds, user, data.pin)
            log_fields = {
                "user_id": user.user_id,
                "session_id": data.session_id,
                "from_account": source.account_num,
                "to_account": target.account_num,
                "amount": data.amount,
                "input_mode": data.input_mode,
                "result": fds,
                "decision": decision,
            }
            if decision in REJECTED:
                # 여기서 예외를 던지면 FDS 기록까지 롤백되므로, 이 트랜잭션은 아무것도 바꾸지 않고 끝낸다
                rejection = decision
            else:
                # 5. 양쪽 balance 변경
                source.balance -= data.amount
                target.balance += data.amount

                # 6. 양쪽 History 한 줄씩 저장
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
                # 7. FDS 기록, 이체에 성공한 기기 등록, 확인 카드는 한 번 쓰면 끝
                await fds_service.save_log(db, **log_fields)
                await fds_service.register_device(db, user.user_id, data.device_fingerprint, client_ip)
                if chat_session is not None:
                    chat_session.state = {
                        **(chat_session.state or {}), "confirmation_jti": None, "pending_transfer": None
                    }
                holder = await user_repository.find_by_id(db, target.user_id)

                return TransferResponse(
                    from_account_num=source.account_num,
                    to_account_num=target.account_num,
                    to_holder_name=holder.name if holder else None,
                    amount=data.amount,
                    balance_after=source.balance,
                    transferred_at=now,
                    risk_level=fds.risk_level.name,
                )

        async with db.begin():
            log = await fds_service.save_log(db, **log_fields)
            extra = fds_service.error_extra(
                log, fds, has_pin=None if rejection == FdsDecision.BLOCKED else user.has_pin
            )
        raise BadRequestException(**REJECTION_ERRORS[rejection], extra=extra)

    async def _check_confirmation(
        self, db: AsyncSession, data: TransferCreate, user_id: int
    ) -> ChatSession | None:
        """session_id가 있으면(채팅에서 온 이체) 확인 카드 토큰이 있어야 하고, 카드 내용과 요청이 같아야 한다.
        PIN 재요청에도 같은 토큰을 쓰도록, 토큰은 이체가 실제로 성공했을 때만 소모한다."""
        if data.session_id is None:
            if data.confirmation_token is not None:
                raise BadRequestException(
                    code="CONFIRMATION_MISMATCH", message="확인 카드와 요청 내용이 다릅니다."
                )
            return None
        session = await chat_repository.find_session(db, data.session_id, for_update=True)
        if session is None or session.user_id != user_id:
            raise NotFoundException(code="CHAT_SESSION_NOT_FOUND", message="대화를 찾을 수 없습니다.")
        if data.confirmation_token is None:
            raise BadRequestException(
                code="CONFIRMATION_REQUIRED", message="확인 카드에서 승인한 이체만 실행할 수 있습니다."
            )
        confirmation = decode_confirmation_token(data.confirmation_token)
        if (
            confirmation.user_id != user_id
            or confirmation.session_id != data.session_id
            or confirmation.from_checking_account_id != data.from_checking_account_id
            or confirmation.to_account_num != data.to_account_num
            or confirmation.amount != data.amount
        ):
            raise BadRequestException(code="CONFIRMATION_MISMATCH", message="확인 카드와 요청 내용이 다릅니다.")
        if (session.state or {}).get("confirmation_jti") != confirmation.jti:
            raise BadRequestException(
                code="CONFIRMATION_USED", message="이미 처리했거나 바뀐 확인 카드입니다. 다시 요청해 주세요."
            )
        return session

    async def _decide(self, fds: FdsResult, user: User, pin: str | None) -> FdsDecision:
        if fds.risk_level == RiskLevel.HIGH:
            return FdsDecision.BLOCKED
        if fds.risk_level == RiskLevel.MEDIUM:
            if pin is None:
                return FdsDecision.AUTH_REQUIRED
            if not await user_service.verify_pin(user, pin):
                return FdsDecision.AUTH_FAILED
            return FdsDecision.PASS_WITH_AUTH
        return FdsDecision.PASS

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
