from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.chat.models import ChatMessage, ChatSession


class ChatRepository:
    async def save(self, db: AsyncSession, obj: ChatSession | ChatMessage) -> None:
        db.add(obj)
        await db.flush()

    async def find_session(
        self, db: AsyncSession, session_id: str, *, for_update: bool = False
    ) -> ChatSession | None:
        return await db.get(ChatSession, session_id, with_for_update=for_update)

    async def find_messages(self, db: AsyncSession, session_id: str, limit: int | None = None) -> list[ChatMessage]:
        """오래된 것부터. limit이 있으면 최근 limit개."""
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.msg_id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(reversed(list(await db.scalars(stmt))))

    async def find_user_texts(self, db: AsyncSession, session_id: str) -> list[str]:
        """FDS 대화 키워드 규칙·LLM 대화 판별용: 이 세션에서 사용자가 보낸 글 전부 (오래된 것부터)"""
        stmt = (
            select(ChatMessage.content)
            .where(ChatMessage.session_id == session_id, ChatMessage.role == "user")
            .order_by(ChatMessage.msg_id)
        )
        return list(await db.scalars(stmt))


chat_repository = ChatRepository()
