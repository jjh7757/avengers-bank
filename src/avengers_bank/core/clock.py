"""현재 시각을 한곳에서 얻는다.

DB에는 UTC로 저장하고, "오늘"(1일 이체 한도, 납입일)은 한국 시간 기준으로 계산한다.
Windows에는 tz 데이터베이스가 없어서 zoneinfo 대신 고정 오프셋을 쓴다 (한국은 서머타임 없음).

시연 모드(DEMO_MODE)에서는 업무 시각을 앞으로 옮길 수 있다 (예: 낮 발표에서 "새벽 2시" 심야 이체 재현).
토큰 만료(JWT)는 옮기지 않은 실제 시각(real_now_utc)을 쓴다.
"""

from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")

_offset = timedelta(0)  # 시연 모드에서 /demo/clock이 바꾼다


def real_now_utc() -> datetime:
    """실제 시각. JWT의 iat·exp처럼 다른 시스템과 맞춰야 하는 값에 쓴다."""
    return datetime.now(timezone.utc)


def now_utc() -> datetime:
    """업무 시각 (거래내역, FDS, 대화 기록). 평소에는 실제 시각과 같다."""
    return real_now_utc() + _offset


def today_kst() -> date:
    return now_utc().astimezone(KST).date()


def start_of_today_utc() -> datetime:
    """한국 시간 오늘 0시를 UTC로 바꾼 값."""
    return datetime.combine(today_kst(), time.min, tzinfo=KST).astimezone(timezone.utc)


def set_demo_hour(kst_hour: int | None) -> datetime:
    """업무 시각을 다음에 오는 한국 시간 kst_hour시 정각으로 옮긴다 (시간은 계속 흐른다). None이면 원래대로.
    과거로는 옮기지 않는다: 이미 쌓인 거래내역보다 앞선 시각이 되면 한도·피처 계산이 꼬이기 때문이다."""
    global _offset
    if kst_hour is None:
        _offset = timedelta(0)
        return now_utc()
    real = real_now_utc().astimezone(KST)
    target = real.replace(hour=kst_hour, minute=0, second=0, microsecond=0)
    if target <= real:
        target += timedelta(days=1)
    _offset = target - real
    return now_utc()


def demo_offset() -> timedelta:
    return _offset
