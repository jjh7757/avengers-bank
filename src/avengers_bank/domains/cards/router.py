from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
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
from avengers_bank.domains.cards.service import card_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/cards", tags=["cards"], responses=error_responses(401, 422))

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]


@router.get("", response_model=SuccessResponse[list[CardSummaryResponse]])
async def get_my_cards(db: Db, current_user: CurrentUser):
    cards = await card_service.get_my_cards(db, current_user)
    return SuccessResponse[list[CardSummaryResponse]](data=cards)


@router.post(
    "/credit",
    response_model=SuccessResponse[CardDetailResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 403, 404),
)
async def issue_credit(data: CreditCardCreate, db: Db, current_user: CurrentUser):
    card = await card_service.issue_credit(db, data, current_user)
    return SuccessResponse[CardDetailResponse](data=card, message="신용카드가 발급되었습니다.")


@router.post(
    "/debit",
    response_model=SuccessResponse[CardDetailResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 403, 404),
)
async def issue_debit(data: DebitCardCreate, db: Db, current_user: CurrentUser):
    card = await card_service.issue_debit(db, data, current_user)
    return SuccessResponse[CardDetailResponse](data=card, message="체크카드가 발급되었습니다.")


@router.get(
    "/{card_type}/{card_id}",
    response_model=SuccessResponse[CardDetailResponse],
    responses=error_responses(403, 404),
)
async def get_card(card_type: CardType, card_id: int, db: Db, current_user: CurrentUser):
    card = await card_service.get_card(db, card_type, card_id, current_user)
    return SuccessResponse[CardDetailResponse](data=card)


@router.get(
    "/{card_type}/{card_id}/histories",
    response_model=SuccessResponse[list[CardHistoryResponse]],
    responses=error_responses(403, 404),
)
async def get_histories(card_type: CardType, card_id: int, db: Db, current_user: CurrentUser):
    histories = await card_service.get_histories(db, card_type, card_id, current_user)
    return SuccessResponse[list[CardHistoryResponse]](data=histories)


@router.post(
    "/{card_type}/{card_id}/payments",
    response_model=SuccessResponse[CardPaymentResponse],
    responses=error_responses(400, 403, 404),
)
async def pay(
    card_type: CardType, card_id: int, data: CardPaymentCreate, db: Db, current_user: CurrentUser
):
    result = await card_service.pay(db, card_type, card_id, data, current_user)
    return SuccessResponse[CardPaymentResponse](data=result, message="결제가 완료되었습니다.")
