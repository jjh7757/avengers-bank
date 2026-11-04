from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.users.models import User


class UserRepository:
    async def save(self, db: AsyncSession, user: User) -> User:
        db.add(user)
        await db.flush()
        return user

    async def find_by_login_id(self, db: AsyncSession, login_id: str) -> User | None:
        return await db.scalar(select(User).where(User.login_id == login_id))

    async def find_by_id(self, db: AsyncSession, user_id: int) -> User | None:
        return await db.get(User, user_id)


user_repository = UserRepository()
