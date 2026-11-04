"""FDS 1단계: 규칙 엔진 (PROJECT_PLAN.md 3.3절). 순수 Python, DB 접근 없음."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

from avengers_bank.core.clock import KST
from avengers_bank.domains.fds.features import TransferContext


class RiskLevel(IntEnum):
    """숫자가 클수록 위험. max()로 합칠 수 있다."""

    LOW = 0
    MEDIUM = 1
    HIGH = 2


@dataclass(frozen=True)
class RuleHit:
    code: str
    name: str
    level: RiskLevel


NEW_RECIPIENT_HIGH_AMOUNT = 1_000_000
NIGHT_HIGH_AMOUNT = 500_000
NIGHT_HOURS = range(0, 6)  # 00:00 ~ 05:59 (한국 시간)
BALANCE_DRAIN_RATIO = 0.9
MEDIUM_HITS_TO_HIGH = 3  # MEDIUM 규칙이 이만큼 겹치면 ML 점수와 무관하게 HIGH


@dataclass(frozen=True)
class Rule:
    code: str
    name: str
    level: RiskLevel
    matches: Callable[[TransferContext], bool]


RULES = [
    Rule(
        "PER_TRANSFER_LIMIT", "1회 이체 한도 초과", RiskLevel.HIGH,
        lambda c: c.per_transfer_limit > 0 and c.amount > c.per_transfer_limit,
    ),
    Rule(
        "DAILY_LIMIT", "1일 이체 한도 초과", RiskLevel.HIGH,
        lambda c: c.daily_transfer_limit > 0 and c.sent_today + c.amount > c.daily_transfer_limit,
    ),
    Rule(
        "NEW_RECIPIENT_HIGH_AMOUNT", "처음 보내는 계좌로 100만원 이상", RiskLevel.MEDIUM,
        lambda c: c.to_account not in c.registered_recipients and c.amount >= NEW_RECIPIENT_HIGH_AMOUNT,
    ),
    Rule(
        "NIGHT_HIGH_AMOUNT", "심야(0~6시) 50만원 이상", RiskLevel.MEDIUM,
        lambda c: c.at.astimezone(KST).hour in NIGHT_HOURS and c.amount >= NIGHT_HIGH_AMOUNT,
    ),
    Rule("NEW_DEVICE", "처음 보는 기기", RiskLevel.MEDIUM, lambda c: c.is_new_device),
    Rule(
        "BALANCE_DRAIN", "잔액의 90% 이상 이체", RiskLevel.MEDIUM,
        lambda c: c.balance > 0 and c.amount >= c.balance * BALANCE_DRAIN_RATIO,
    ),
    Rule(
        "REPEATED_ATTEMPT", "차단 직후 재시도", RiskLevel.HIGH,
        lambda c: c.rejected_recently_in_session,
    ),
    Rule(
        "CONVERSATION_KEYWORD", "대화에 보이스피싱 의심 표현", RiskLevel.MEDIUM,
        lambda c: c.session_keyword_count > 0,
    ),
]


def evaluate_rules(ctx: TransferContext) -> list[RuleHit]:
    return [RuleHit(rule.code, rule.name, rule.level) for rule in RULES if rule.matches(ctx)]


def rule_level(hits: list[RuleHit]) -> RiskLevel:
    level = max((hit.level for hit in hits), default=RiskLevel.LOW)
    if sum(hit.level == RiskLevel.MEDIUM for hit in hits) >= MEDIUM_HITS_TO_HIGH:
        level = RiskLevel.HIGH
    return level
