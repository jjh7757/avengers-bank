import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.clock import now_utc
from avengers_bank.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from avengers_bank.domains.accounts.models import CheckingAccountHistory, HistoryType
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.cards.models import (
    CreditCard,
    CreditCardHistory,
    DebitCard,
    DebitCardHistory,
)
from avengers_bank.domains.cards.repository import (
    HISTORY_MODELS,
    Card,
    CardHistory,
    card_id_of,
    card_repository,
)
from avengers_bank.domains.cards.schemas import (
    CardDetailResponse,
    CardHistoryResponse,
    CardPaymentCreate,
    CardPaymentResponse,
    CardSummaryResponse,
    CardType,
    CreditCardCreate,
    DebitCardCreate,
)
from avengers_bank.domains.products.service import product_service
from avengers_bank.domains.users.schemas import UserResponse

# 카드번호 형식: 9410-XXXX-XXXX-XXXX (신용), 9420-… (체크)
CARD_NUM_PREFIX = {"credit": "9410", "debit": "9420"}
MAX_ISSUE_ATTEMPTS = 10


def to_summary(card_type: str, card: Card) -> CardSummaryResponse:
    return CardSummaryResponse(
        card_type=card_type,
        card_id=card_id_of(card_type, card),
        card_num=card.card_num,
        checking_account_id=card.checking_account_id,
        accumulated_amount=card.accumulated_amount,
    )


def to_detail(card_type: str, card: Card) -> CardDetailResponse:
    return CardDetailResponse(
        **to_summary(card_type, card).model_dump(),
        product_id=card.product_id,
        payment_date=getattr(card, "payment_date", None),
    )


def to_history(card_type: str, history: CardHistory) -> CardHistoryResponse:
    return CardHistoryResponse(
        history_id=getattr(history, f"{card_type}_card_history_id"),
        place_of_use=history.place_of_use,
        used_amount=history.used_amount,
        time=history.time,
    )


class CardService:
    async def issue_credit(
        self, db: AsyncSession, data: CreditCardCreate, current_user: UserResponse
    ) -> CardDetailResponse:
        async with db.begin():
            await self._validate_issue(db, "credit", data.product_id, data.checking_account_id, current_user)
            card = CreditCard(
                user_id=current_user.user_id,
                product_id=data.product_id,
                checking_account_id=data.checking_account_id,
                card_num=await self._issue_card_num(db, "credit"),
                accumulated_amount=0,
                payment_date=data.payment_date,
            )
            await card_repository.save(db, card)
            return to_detail("credit", card)

    async def issue_debit(
        self, db: AsyncSession, data: DebitCardCreate, current_user: UserResponse
    ) -> CardDetailResponse:
        async with db.begin():
            await self._validate_issue(db, "debit", data.product_id, data.checking_account_id, current_user)
            card = DebitCard(
                user_id=current_user.user_id,
                product_id=data.product_id,
                checking_account_id=data.checking_account_id,
                card_num=await self._issue_card_num(db, "debit"),
                accumulated_amount=0,
            )
            await card_repository.save(db, card)
            return to_detail("debit", card)

    async def get_my_cards(
        self, db: AsyncSession, current_user: UserResponse
    ) -> list[CardSummaryResponse]:
        async with db.begin():
            cards = await card_repository.find_all_by_user_id(db, current_user.user_id)
            return [to_summary(card_type, card) for card_type, card in cards]

    async def get_card(
        self, db: AsyncSession, card_type: CardType, card_id: int, current_user: UserResponse
    ) -> CardDetailResponse:
        async with db.begin():
            card = await self._get_owned_card(db, card_type, card_id, current_user.user_id)
            return to_detail(card_type, card)

    async def get_histories(
        self, db: AsyncSession, card_type: CardType, card_id: int, current_user: UserResponse
    ) -> list[CardHistoryResponse]:
        async with db.begin():
            await self._get_owned_card(db, card_type, card_id, current_user.user_id)
            histories = await card_repository.find_histories(db, card_type, card_id)
            return [to_history(card_type, history) for history in histories]

    async def pay(
        self,
        db: AsyncSession,
        card_type: CardType,
        card_id: int,
        data: CardPaymentCreate,
        current_user: UserResponse,
    ) -> CardPaymentResponse:
        now = now_utc()
        account_balance_after = None
        async with db.begin():
            card = await self._get_owned_card(
                db, card_type, card_id, current_user.user_id, for_update=True
            )

            # 체크카드: 연결 계좌 잔액 검사 → 출금 → CheckingAccountHistory 저장
            if card_type == "debit":
                account = await account_service.get_owned_account(
                    db, "checking", card.checking_account_id, current_user.user_id, for_update=True
                )
                if account.balance < data.used_amount:
                    raise BadRequestException(code="INSUFFICIENT_BALANCE", message="잔액이 부족합니다.")
                account.balance -= data.used_amount
                account_balance_after = account.balance
                await account_repository.save(
                    db,
                    CheckingAccountHistory(
                        checking_account_id=account.checking_account_id,
                        date=now,
                        change_amount=-data.used_amount,
                        type=HistoryType.CARD_PAYMENT,
                        from_account=account.account_num,
                    ),
                )

            # 공통: 카드 History 저장 + accumulated_amount 증가
            history_model: type[CreditCardHistory | DebitCardHistory] = HISTORY_MODELS[card_type]
            await card_repository.save(
                db,
                history_model(
                    **{f"{card_type}_card_id": card_id},
                    place_of_use=data.place_of_use,
                    used_amount=data.used_amount,
                    time=now,
                ),
            )
            card.accumulated_amount += data.used_amount

            return CardPaymentResponse(
                card_type=card_type,
                card_id=card_id,
                place_of_use=data.place_of_use,
                used_amount=data.used_amount,
                accumulated_amount=card.accumulated_amount,
                account_balance_after=account_balance_after,
                paid_at=now,
            )

    async def _validate_issue(
        self,
        db: AsyncSession,
        card_type: CardType,
        product_id: int,
        checking_account_id: int,
        current_user: UserResponse,
    ) -> None:
        await product_service.validate_card_product(db, product_id, card_type.upper())
        # 연결할 계좌가 본인 입출금 계좌인지 확인
        await account_service.get_owned_account(
            db, "checking", checking_account_id, current_user.user_id
        )

    async def _get_owned_card(
        self,
        db: AsyncSession,
        card_type: CardType,
        card_id: int,
        user_id: int,
        *,
        for_update: bool = False,
    ) -> Card:
        card = await card_repository.find_by_id(db, card_type, card_id, for_update=for_update)
        if card is None:
            raise NotFoundException(code="CARD_NOT_FOUND", message="카드를 찾을 수 없습니다.")
        if card.user_id != user_id:
            raise ForbiddenException(code="CARD_FORBIDDEN", message="본인 카드가 아닙니다.")
        return card

    async def _issue_card_num(self, db: AsyncSession, card_type: str) -> str:
        """카드번호는 여기서만 발급한다. 신용·체크 2개 테이블을 모두 검사한다."""
        prefix = CARD_NUM_PREFIX[card_type]
        for _ in range(MAX_ISSUE_ATTEMPTS):
            groups = [f"{secrets.randbelow(10_000):04d}" for _ in range(3)]
            card_num = "-".join([prefix, *groups])
            if not await card_repository.exists_by_card_num(db, card_num):
                return card_num
        raise ConflictException(
            code="CARD_NUM_ISSUE_FAILED", message="카드번호 발급에 실패했습니다. 다시 시도해 주세요."
        )


card_service = CardService()
