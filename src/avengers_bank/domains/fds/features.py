"""FDS 입력(TransferContext)과 피처 계산.

합성 데이터 생성기(fds_training/generate_data.py)와 서비스(fds/service.py)가 이 파일의 같은 함수를 쓴다.
학습 때와 운영 때 피처 계산이 달라지는 문제(training-serving skew)를 막기 위해서다.
이 파일은 DB나 FastAPI를 import하지 않는다.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from avengers_bank.core.clock import KST

VOICE_PHISHING_KEYWORDS = (
    "검찰",
    "금감원",
    "금융감독원",
    "경찰",
    "수사",
    "안전계좌",
    "보호계좌",
    "대포통장",
    "명의도용",
    "시키는 대로",
    "아무에게도 말하지",
    "구속",
    "대출 승인",
)


def count_keywords(texts: list[str]) -> int:
    """세션 메시지들에서 보이스피싱 키워드가 몇 번 나왔는지 센다."""
    joined = " ".join(texts).replace(" ", "")
    return sum(joined.count(keyword.replace(" ", "")) for keyword in VOICE_PHISHING_KEYWORDS)


@dataclass(frozen=True)
class PastTransfer:
    at: datetime  # UTC
    amount: int
    to_account: str


@dataclass
class TransferContext:
    """이체 한 건을 판정하는 데 필요한 모든 정보. 시각은 모두 timezone-aware UTC."""

    at: datetime
    amount: int
    to_account: str
    balance: int  # 이체 전 잔액
    user_created_at: datetime
    past_transfers: list[PastTransfer] = field(default_factory=list)  # 최근 30일, at 이전, 사용자 전체 계좌
    registered_recipients: set[str] = field(default_factory=set)
    is_new_device: bool = False
    session_attempt_count: int = 0  # 이 세션에서 이번 요청 전에 시도한 이체 수
    session_rejected_count: int = 0  # 이 세션에서 차단된 이체 수
    session_keyword_count: int = 0
    # 규칙 엔진 전용
    per_transfer_limit: int = 0
    daily_transfer_limit: int = 0
    sent_today: int = 0
    rejected_recently_in_session: bool = False  # 같은 세션에서 5분 안에 차단된 적 있음
    to_own_account: bool = False  # 받는 계좌가 내 다른 계좌 (내 돈을 옮기는 것)
    conversation_risk: str | None = None  # LLM 대화 판별 none / suspicious / scam, 판별 못 했으면 None
    conversation_reason: str | None = None


FEATURE_NAMES = [
    "amount",
    "log_amount",
    "hour",
    "weekday",
    "amount_to_balance",
    "amount_vs_30d_avg",
    "hour_diff_from_usual",
    "transfers_7d",
    "is_new_recipient",
    "recipient_send_count",
    "days_since_last_send_to_recipient",
    "is_new_device",
    "account_age_days",
    "session_attempt_count",
    "session_rejected_count",
    "session_keyword_count",
    "count_1h",
    "sum_1h",
    "count_24h",
    "sum_24h",
]

# 차단 사유 화면·SHAP 설명에 쓰는 한국어 이름
FEATURE_LABELS = {
    "amount": "이체 금액",
    "log_amount": "이체 금액",
    "hour": "이체 시간대",
    "weekday": "요일",
    "amount_to_balance": "잔액 대비 이체 비율",
    "amount_vs_30d_avg": "평소 대비 이체 금액",
    "hour_diff_from_usual": "평소와 다른 시간대",
    "transfers_7d": "최근 7일 이체 횟수",
    "is_new_recipient": "처음 보내는 계좌",
    "recipient_send_count": "이 계좌로 보낸 횟수",
    "days_since_last_send_to_recipient": "이 계좌로 마지막 송금 후 경과일",
    "is_new_device": "새 기기",
    "account_age_days": "가입 후 경과일",
    "session_attempt_count": "대화 중 이체 시도 횟수",
    "session_rejected_count": "대화 중 거절된 이체 횟수",
    "session_keyword_count": "대화 속 보이스피싱 의심 표현",
    "count_1h": "최근 1시간 이체 횟수",
    "sum_1h": "최근 1시간 이체 합계",
    "count_24h": "최근 24시간 이체 횟수",
    "sum_24h": "최근 24시간 이체 합계",
}


def _circular_hour_diff(a: float, b: float) -> float:
    diff = abs(a - b) % 24
    return min(diff, 24 - diff)


def compute_features(ctx: TransferContext) -> dict[str, float]:
    """FEATURE_NAMES 순서의 dict. 값이 없으면 NaN (LightGBM이 결측으로 처리)."""
    local = ctx.at.astimezone(KST)
    hour = local.hour + local.minute / 60
    past = [p for p in ctx.past_transfers if p.at < ctx.at and p.at >= ctx.at - timedelta(days=30)]

    def window(delta: timedelta) -> list[PastTransfer]:
        return [p for p in past if p.at >= ctx.at - delta]

    avg_30d = sum(p.amount for p in past) / len(past) if past else math.nan
    usual_hour = math.nan
    if past:
        # 시각의 평균은 원 위에서 구한다 (23시와 1시의 평균은 0시)
        angles = [(p.at.astimezone(KST).hour + p.at.astimezone(KST).minute / 60) / 24 * 2 * math.pi for p in past]
        mean_angle = math.atan2(
            sum(math.sin(a) for a in angles) / len(angles),
            sum(math.cos(a) for a in angles) / len(angles),
        )
        usual_hour = (mean_angle / (2 * math.pi) * 24) % 24

    to_recipient = [p for p in past if p.to_account == ctx.to_account]
    last_1h, last_24h = window(timedelta(hours=1)), window(timedelta(hours=24))

    return {
        "amount": float(ctx.amount),
        "log_amount": math.log10(ctx.amount + 1),
        "hour": hour,
        "weekday": float(local.weekday()),
        "amount_to_balance": ctx.amount / ctx.balance if ctx.balance > 0 else math.nan,
        "amount_vs_30d_avg": ctx.amount / avg_30d if past else math.nan,
        "hour_diff_from_usual": _circular_hour_diff(hour, usual_hour) if past else math.nan,
        "transfers_7d": float(len(window(timedelta(days=7)))),
        "is_new_recipient": float(ctx.to_account not in ctx.registered_recipients),
        "recipient_send_count": float(len(to_recipient)),
        "days_since_last_send_to_recipient": (
            (ctx.at - max(p.at for p in to_recipient)).total_seconds() / 86400 if to_recipient else math.nan
        ),
        "is_new_device": float(ctx.is_new_device),
        "account_age_days": max((ctx.at - ctx.user_created_at).total_seconds() / 86400, 0.0),
        "session_attempt_count": float(ctx.session_attempt_count),
        "session_rejected_count": float(ctx.session_rejected_count),
        "session_keyword_count": float(ctx.session_keyword_count),
        "count_1h": float(len(last_1h)),
        "sum_1h": float(sum(p.amount for p in last_1h)),
        "count_24h": float(len(last_24h)),
        "sum_24h": float(sum(p.amount for p in last_24h)),
    }


def to_vector(features: dict[str, float]) -> list[float]:
    return [features[name] for name in FEATURE_NAMES]
