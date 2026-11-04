from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.fds.models import FdsDecision, FdsLog, UserDevice


class FdsRepository:
    async def save_log(self, db: AsyncSession, log: FdsLog) -> None:
        db.add(log)
        await db.flush()

    async def find_logs_by_user_id(self, db: AsyncSession, user_id: int, limit: int) -> list[FdsLog]:
        stmt = (
            select(FdsLog)
            .where(FdsLog.user_id == user_id)
            .order_by(FdsLog.created_at.desc(), FdsLog.fds_log_id.desc())
            .limit(limit)
        )
        return list(await db.scalars(stmt))

    async def count_session_logs(
        self, db: AsyncSession, user_id: int, session_id: str, *, decision: FdsDecision | None = None,
        since: datetime | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(FdsLog).where(
            FdsLog.user_id == user_id, FdsLog.session_id == session_id
        )
        if decision is not None:
            stmt = stmt.where(FdsLog.decision == decision)
        if since is not None:
            stmt = stmt.where(FdsLog.created_at >= since)
        return int(await db.scalar(stmt))

    async def find_devices(self, db: AsyncSession, user_id: int) -> list[UserDevice]:
        return list(await db.scalars(select(UserDevice).where(UserDevice.user_id == user_id)))

    async def touch_device(
        self, db: AsyncSession, user_id: int, fingerprint: str, ip: str | None, now: datetime
    ) -> None:
        device = await db.scalar(
            select(UserDevice).where(
                UserDevice.user_id == user_id, UserDevice.device_fingerprint == fingerprint
            )
        )
        if device is None:
            db.add(UserDevice(user_id=user_id, device_fingerprint=fingerprint, ip=ip, first_seen=now, last_seen=now))
        else:
            device.ip, device.last_seen = ip, now
        await db.flush()


fds_repository = FdsRepository()
