"""타행 이체 백그라운드 태스크. 앱 lifespan에서 시작한다 (허브 설정이 있을 때만).

confirm_loop          처리 중(PENDING) 타행 이체를 주기적으로 허브에 확인하고, 열린 예치금 신청(SPEC 10.9)의
                      결정을 확인한 뒤 내부 계정을 대사한다
settlement_sync_loop  허브 정산 run을 우리 장부와 맞추고, 확정된 run이 맞으면 장부를 정리한다 (SPEC 10.6)
"""

import asyncio
import logging

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank import reserve_requests
from avengers_bank.domains.interbank.service import confirm_pending, reconcile
from avengers_bank.domains.interbank.settlement_sync import sync_settlements

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
                if await reserve_requests.has_open(db):  # 열린 신청이 없으면 허브를 부르지 않는다
                    for req in await reserve_requests.sync(db):
                        logger.info("허브 예치금 신청 #%s → %s", req.request_id, req.status)
            async with SessionLocal() as db:
                mismatches = await reconcile(db)
            if mismatches:  # 돈이 어딘가에서 새거나 생겼다: 사람이 봐야 한다 (Sentry로도 간다)
                logger.error("타행 내부 계정 대사 불일치: %s", "; ".join(mismatches))
        except Exception:  # 태스크가 죽으면 확인이 영영 멈추므로 기록만 하고 계속 돈다
            logger.exception("타행 이체 확인 태스크 오류")


async def settlement_sync_loop() -> None:
    """시작 뒤 한 번(꺼져 있던 동안 놓친 run을 이어서, SPEC 10.6의 5), 그 뒤 간격마다 허브 정산을 대사한다."""
    settings = get_settings()
    await asyncio.sleep(settings.interbank_settlement_sync_startup_delay_seconds)
    while True:
        try:
            async with SessionLocal() as db:
                rows = await sync_settlements(db)
            if rows:
                logger.info("허브 정산 대사: %s", ", ".join(f"run {r.hub_run_id} {r.result}" for r in rows))
        except Exception:  # 태스크가 죽으면 대사가 영영 멈추므로 기록만 하고 계속 돈다
            logger.exception("허브 정산 대사 태스크 오류")
        await asyncio.sleep(settings.interbank_settlement_sync_interval_seconds)
