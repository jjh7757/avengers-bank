from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.speech.models import VoiceProfile


class VoiceRepository:
    async def find(self, db: AsyncSession, user_id: int) -> VoiceProfile | None:
        return await db.get(VoiceProfile, user_id)

    async def save(self, db: AsyncSession, profile: VoiceProfile) -> None:
        db.add(profile)
        await db.flush()

    async def delete(self, db: AsyncSession, profile: VoiceProfile) -> None:
        await db.delete(profile)
        await db.flush()


voice_repository = VoiceRepository()
