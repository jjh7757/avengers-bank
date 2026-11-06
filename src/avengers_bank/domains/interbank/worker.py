"""처리 중(PENDING) 타행 이체를 주기적으로 허브에 확인한다. 앱 lifespan에서 시작한다 (허브 설정이 있을 때만)."""

import asyncio
import logging

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank.service import confirm_pending, reconcile

logger = logging.getLogger(__name__)


async def confirm_loop() -> None:
    interval = get_settings().interbank_confirm_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as db:
                confirmed = await confirm_pending(db)
            if confirmed:
                logger.info("처리 중 타행 이체 %d건 확정", confirmed)
            async with SessionLocal() as db:
                mismatches = await reconcile(db)
            if mismatches:  # 돈이 어딘가에서 새거나 생겼다: 사람이 봐야 한다 (Sentry로도 간다)
                logger.error("타행 내부 계정 대사 불일치: %s", "; ".join(mismatches))
        except Exception:  # 태스크가 죽으면 확인이 영영 멈추므로 기록만 하고 계속 돈다
            logger.exception("타행 이체 확인 태스크 오류")
