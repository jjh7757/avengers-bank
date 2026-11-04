"""시연 모드 API. `.env`의 DEMO_MODE=true일 때만 동작하고, 아니면 404.

발표장에서 낮에 "새벽 2시 이체"(심야 고액 규칙)를 재현하려고 업무 시각을 옮긴다.
로그인 없이 서버 전체 시각이 바뀌므로 발표용 로컬 서버에서만 켠다.
"""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from avengers_bank.core.clock import KST, demo_offset, now_utc, set_demo_hour
from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import NotFoundException
from avengers_bank.core.responses import SuccessResponse

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoClockUpdate(BaseModel):
    kst_hour: int | None = Field(default=None, ge=0, le=23, description="옮길 한국 시간(시). null이면 실제 시각으로")


class DemoStatus(BaseModel):
    demo_mode: bool
    now_kst: datetime  # 업무 시각
    shifted: bool  # 실제 시각에서 옮겼는지


def status() -> DemoStatus:
    return DemoStatus(
        demo_mode=get_settings().demo_mode,
        now_kst=now_utc().astimezone(KST),
        shifted=demo_offset().total_seconds() != 0,
    )


@router.get("/status", response_model=SuccessResponse[DemoStatus])
async def get_status():
    """시연 모드 여부와 지금 업무 시각 (화면 상단에 시연 시각을 표시하는 데 쓴다)"""
    return SuccessResponse[DemoStatus](data=status())


@router.post("/clock", response_model=SuccessResponse[DemoStatus])
async def set_clock(data: DemoClockUpdate):
    if not get_settings().demo_mode:
        raise NotFoundException()
    set_demo_hour(data.kst_hour)
    message = "실제 시각으로 돌렸어요." if data.kst_hour is None else f"업무 시각을 {data.kst_hour}시로 옮겼어요."
    return SuccessResponse[DemoStatus](data=status(), message=message)
