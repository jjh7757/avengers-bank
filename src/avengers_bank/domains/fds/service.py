"""FDS 판정: 규칙 엔진(rules.py) + LightGBM(scorer.py) → LOW / MEDIUM / HIGH.

transfers.service가 이체 트랜잭션 안에서 evaluate()를 부르고,
결과와 PIN 확인 여부로 결정(FdsDecision)을 내린 뒤 save_log()로 기록한다.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.clock import now_utc
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.fds.conversation import ConversationRisk
from avengers_bank.domains.fds.features import (
    PastTransfer,
    TransferContext,
    compute_features,
    count_keywords,
)
from avengers_bank.domains.fds.models import FdsDecision, FdsLog
from avengers_bank.domains.fds.repository import fds_repository
from avengers_bank.domains.fds.rules import RiskLevel, RuleHit, evaluate_rules, rule_level
from avengers_bank.domains.fds.scorer import Factor, fds_scorer
from avengers_bank.domains.recipients.repository import recipient_repository
from avengers_bank.domains.users.models import User

HISTORY_WINDOW = timedelta(days=30)
REPEATED_ATTEMPT_WINDOW = timedelta(minutes=5)
PHISHING_WARNING = (
    "금융기관·검찰·경찰·금융감독원은 전화나 메시지로 송금을 요구하지 않습니다. "
    "누군가의 지시를 받고 이체하는 중이라면 지금 멈추고 112 또는 1332(금융감독원)에 확인하세요."
)


def as_utc(value: datetime) -> datetime:
    """SQLite는 timezone 정보 없이 돌려준다. 저장할 때 UTC로 넣었으므로 UTC로 붙인다."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@dataclass
class FdsResult:
    risk_level: RiskLevel
    rule_hits: list[RuleHit]
    ml_score: float | None
    top_factors: list[Factor]

    def rule_hits_json(self) -> list[dict]:
        return [
            {"code": h.code, "name": h.name, "level": h.level.name, **({"detail": h.detail} if h.detail else {})}
            for h in self.rule_hits
        ]

    def top_factors_json(self) -> list[dict]:
        return [asdict(f) for f in self.top_factors]


class FdsService:
    async def evaluate(
        self,
        db: AsyncSession,
        *,
        user: User,
        source: CheckingAccount,
        to_account_num: str,
        amount: int,
        sent_today: int,
        session_id: str | None,
        device_fingerprint: str | None,
        session_texts: list[str],
        conversation: ConversationRisk | None = None,
        to_own_account: bool = False,
    ) -> FdsResult:
        """to_own_account: 우리 은행 밖의 내 계좌 (허브가 같은 사람으로 확인, SPEC 9절). 내 계좌처럼 본다."""
        now = now_utc()
        past = await account_repository.find_user_transfer_outs_since(db, user.user_id, now - HISTORY_WINDOW)
        known_devices = {d.device_fingerprint for d in await fds_repository.find_devices(db, user.user_id)}
        own_accounts = {
            account.account_num for kind, account in await account_repository.find_all_by_user_id(db, user.user_id)
            if kind == "checking"
        }

        attempts = rejected = 0
        rejected_recently = False
        if session_id:
            attempts = await fds_repository.count_session_logs(db, user.user_id, session_id)
            rejected = await fds_repository.count_session_logs(
                db, user.user_id, session_id, decision=FdsDecision.BLOCKED
            )
            rejected_recently = bool(rejected) and bool(
                await fds_repository.count_session_logs(
                    db, user.user_id, session_id, decision=FdsDecision.BLOCKED,
                    since=now - REPEATED_ATTEMPT_WINDOW,
                )
            )

        ctx = TransferContext(
            at=now,
            amount=amount,
            to_account=to_account_num,
            balance=source.balance,
            user_created_at=as_utc(user.created_at),
            past_transfers=[PastTransfer(as_utc(at), amt, to or "") for at, amt, to in past],
            # 내 계좌는 처음 보내는 계좌가 아니다 (ML 피처 "새 수취인"에도 같은 기준)
            registered_recipients=await recipient_repository.find_account_nums(db, user.user_id) | own_accounts
            | ({to_account_num} if to_own_account else set()),
            # 처음 쓰는 사용자(등록 기기 0개)는 새 기기로 보지 않는다. 기기 정보를 안 보내면 모르는 기기로 본다.
            is_new_device=bool(known_devices) and device_fingerprint not in known_devices,
            session_attempt_count=attempts,
            session_rejected_count=rejected,
            session_keyword_count=count_keywords(session_texts),
            per_transfer_limit=source.per_transfer_limit,
            daily_transfer_limit=source.daily_transfer_limit,
            sent_today=sent_today,
            rejected_recently_in_session=rejected_recently,
            to_own_account=to_own_account or to_account_num in own_accounts,
            conversation_risk=conversation.risk if conversation else None,
            conversation_reason=conversation.reason if conversation else None,
        )

        hits = evaluate_rules(ctx)
        score = fds_scorer.score(compute_features(ctx))
        level = rule_level(hits)
        if score is not None:
            if score.value >= fds_scorer.high_threshold:
                level = max(level, RiskLevel.HIGH)
            elif score.value >= fds_scorer.medium_threshold:
                level = max(level, RiskLevel.MEDIUM)
        return FdsResult(
            risk_level=level,
            rule_hits=hits,
            ml_score=round(score.value, 4) if score else None,
            top_factors=score.top_factors if score else [],
        )

    async def save_log(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        session_id: str | None,
        from_account: str,
        to_account: str,
        amount: int,
        result: FdsResult,
        decision: FdsDecision,
    ) -> FdsLog:
        log = FdsLog(
            user_id=user_id,
            session_id=session_id,
            tx_type="TRANSFER",
            from_account=from_account,
            to_account=to_account,
            amount=amount,
            rule_hits=result.rule_hits_json(),
            ml_score=result.ml_score,
            top_factors=result.top_factors_json(),
            risk_level=result.risk_level.name,
            decision=decision,
            created_at=now_utc(),
        )
        await fds_repository.save_log(db, log)
        return log

    async def register_device(
        self, db: AsyncSession, user_id: int, device_fingerprint: str | None, ip: str | None
    ) -> None:
        """이체에 성공한 기기만 등록한다."""
        if device_fingerprint:
            await fds_repository.touch_device(db, user_id, device_fingerprint, ip, now_utc())

    def error_extra(self, log: FdsLog, result: FdsResult, *, has_pin: bool | None = None) -> dict:
        """차단·추가 인증 응답의 error.extra. 프론트가 사유와 경고를 보여 준다."""
        extra = {
            "fds_log_id": log.fds_log_id,
            "risk_level": result.risk_level.name,
            "rule_hits": result.rule_hits_json(),
            "ml_score": result.ml_score,
            "top_factors": result.top_factors_json(),
        }
        if result.risk_level == RiskLevel.HIGH:
            extra["warning"] = PHISHING_WARNING
        if has_pin is not None:
            extra["has_pin"] = has_pin
        return extra

    async def get_my_logs(self, db: AsyncSession, user_id: int, limit: int) -> list[FdsLog]:
        async with db.begin():
            return await fds_repository.find_logs_by_user_id(db, user_id, limit)


fds_service = FdsService()
