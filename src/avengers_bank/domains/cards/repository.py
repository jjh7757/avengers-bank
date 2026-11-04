from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.cards.models import (
    CreditCard,
    CreditCardHistory,
    DebitCard,
    DebitCardHistory,
)

type Card = CreditCard | DebitCard
type CardHistory = CreditCardHistory | DebitCardHistory

CARD_MODELS: dict[str, type[Card]] = {"credit": CreditCard, "debit": DebitCard}
HISTORY_MODELS: dict[str, type[CardHistory]] = {
    "credit": CreditCardHistory,
    "debit": DebitCardHistory,
}


def card_id_of(card_type: str, obj: Card | CardHistory) -> int:
    return getattr(obj, f"{card_type}_card_id")


class CardRepository:
    async def save(self, db: AsyncSession, obj: Card | CardHistory) -> None:
        db.add(obj)
        await db.flush()

    async def find_by_id(
        self, db: AsyncSession, card_type: str, card_id: int, *, for_update: bool = False
    ) -> Card | None:
        return await db.get(CARD_MODELS[card_type], card_id, with_for_update=for_update)

    async def find_all_by_user_id(self, db: AsyncSession, user_id: int) -> list[tuple[str, Card]]:
        cards = []
        for card_type, model in CARD_MODELS.items():
            rows = await db.scalars(
                select(model).where(model.user_id == user_id).order_by(getattr(model, f"{card_type}_card_id"))
            )
            cards += [(card_type, row) for row in rows]
        return cards

    async def exists_by_card_num(self, db: AsyncSession, card_num: str) -> bool:
        for model in CARD_MODELS.values():
            if await db.scalar(select(model.card_num).where(model.card_num == card_num)):
                return True
        return False

    async def find_histories(
        self, db: AsyncSession, card_type: str, card_id: int
    ) -> list[CardHistory]:
        model = HISTORY_MODELS[card_type]
        stmt = (
            select(model)
            .where(getattr(model, f"{card_type}_card_id") == card_id)
            .order_by(model.time.desc(), getattr(model, f"{card_type}_card_history_id").desc())
        )
        return list(await db.scalars(stmt))


card_repository = CardRepository()
