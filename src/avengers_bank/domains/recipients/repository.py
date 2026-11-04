from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.recipients.models import Recipient


class RecipientRepository:
    async def save(self, db: AsyncSession, recipient: Recipient) -> None:
        db.add(recipient)
        await db.flush()

    async def delete(self, db: AsyncSession, recipient: Recipient) -> None:
        await db.delete(recipient)
        await db.flush()

    async def find_by_id(self, db: AsyncSession, recipient_id: int) -> Recipient | None:
        return await db.get(Recipient, recipient_id)

    async def find_all_by_user_id(self, db: AsyncSession, user_id: int) -> list[Recipient]:
        stmt = (
            select(Recipient)
            .where(Recipient.user_id == user_id)
            .order_by(Recipient.last_sent_at.desc().nulls_last(), Recipient.recipient_id)
        )
        return list(await db.scalars(stmt))

    async def find_by_nickname(
        self, db: AsyncSession, user_id: int, nickname: str
    ) -> Recipient | None:
        return await db.scalar(
            select(Recipient).where(Recipient.user_id == user_id, Recipient.nickname == nickname)
        )

    async def find_by_account_num(
        self, db: AsyncSession, user_id: int, account_num: str
    ) -> Recipient | None:
        return await db.scalar(
            select(Recipient).where(
                Recipient.user_id == user_id, Recipient.account_num == account_num
            )
        )

    async def find_account_nums(self, db: AsyncSession, user_id: int) -> set[str]:
        """FDS의 "처음 보내는 계좌" 판정용"""
        return set(await db.scalars(select(Recipient.account_num).where(Recipient.user_id == user_id)))

    async def touch_last_sent_at(
        self, db: AsyncSession, user_id: int, account_num: str, sent_at: datetime
    ) -> None:
        """등록된 수취인에게 보냈으면 마지막 송금 시각을 갱신한다. 등록 안 된 계좌면 아무 일도 없음."""
        await db.execute(
            update(Recipient)
            .where(Recipient.user_id == user_id, Recipient.account_num == account_num)
            .values(last_sent_at=sent_at)
        )


recipient_repository = RecipientRepository()
