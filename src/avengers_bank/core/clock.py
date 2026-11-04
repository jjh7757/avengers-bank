"""현재 시각을 한곳에서 얻는다.

DB에는 UTC로 저장하고, "오늘"(1일 이체 한도, 납입일)은 한국 시간 기준으로 계산한다.
Windows에는 tz 데이터베이스가 없어서 zoneinfo 대신 고정 오프셋을 쓴다 (한국은 서머타임 없음).
"""

from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_kst() -> date:
    return now_utc().astimezone(KST).date()


def start_of_today_utc() -> datetime:
    """한국 시간 오늘 0시를 UTC로 바꾼 값."""
    return datetime.combine(today_kst(), time.min, tzinfo=KST).astimezone(timezone.utc)
