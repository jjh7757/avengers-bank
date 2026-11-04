"""FDS 학습용 합성 이체 데이터 생성기.

정상 사용자 500명의 3개월(2026-07 ~ 2026-09) 이체를 평소 패턴대로 만들고,
사기 시나리오 3종(계정 탈취, 보이스피싱, 테스트 송금 후 고액)을 약 1~2% 섞는다.
피처는 서비스와 같은 avengers_bank.domains.fds.features.compute_features로 계산한다.

사용법 (avengers_bank 폴더에서):
    uv run --group fds python fds_training/generate_data.py
출력: fds_training/data/{transactions,train,valid}.parquet
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from avengers_bank.core.clock import KST
from avengers_bank.domains.fds.features import (
    FEATURE_NAMES,
    PastTransfer,
    TransferContext,
    compute_features,
)

SEED = 42
N_USERS = 500
N_FRAUD_CASES = 170
START = datetime(2026, 7, 1, tzinfo=KST)
END = datetime(2026, 10, 1, tzinfo=KST)
VALID_FROM = datetime(2026, 9, 1, tzinfo=KST)  # 앞 2개월 train, 뒤 1개월 valid
OUT_DIR = Path(__file__).resolve().parent / "data"

rng = np.random.default_rng(SEED)


def new_account_num() -> str:
    return f"110-{rng.integers(1000):03d}-{rng.integers(1_000_000):06d}"


def round_won(amount: float, unit: int = 1000) -> int:
    return max(unit, int(round(amount / unit)) * unit)


def at_kst(day: datetime, hour: float) -> datetime:
    hour = hour % 24
    return (day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=hour)).astimezone(
        KST
    )


@dataclass
class Event:
    at: datetime
    kind: str  # salary / transfer
    amount: int = 0
    to_account: str = ""
    label: int = 0
    scenario: str = "normal"
    new_device: bool = False
    voice: bool = False
    attempts: int = 0
    rejected: int = 0
    keywords: int = 0
    drain_ratio: float | None = None  # 사기: 그 시점 잔액의 비율로 금액을 정한다


@dataclass
class User:
    user_id: int
    created_at: datetime
    usual_hour: float
    voice_prob: float
    salary: int
    payday: int
    balance: int
    recipients: list[str]
    recipient_weights: np.ndarray
    events: list[Event] = field(default_factory=list)


def make_user(user_id: int) -> User:
    elderly = rng.random() < 0.3
    night_owl = rng.random() < 0.08
    usual_hour = rng.normal(11, 1.5) if elderly else rng.normal(15, 3)
    if night_owl:
        usual_hour = rng.normal(23.5, 1.0)
    salary = round_won(rng.uniform(2_200_000, 6_500_000), 10_000)
    n_recipients = int(rng.integers(2, 8))
    weights = rng.dirichlet(np.ones(n_recipients) * 0.8)
    created = START - timedelta(days=float(rng.uniform(5, 1500)))
    return User(
        user_id=user_id,
        created_at=created,
        usual_hour=float(usual_hour),
        voice_prob=0.6 if elderly else 0.05,
        salary=salary,
        payday=int(rng.choice([10, 15, 25])),
        balance=round_won(salary * rng.uniform(0.3, 3.0), 10_000),
        recipients=[new_account_num() for _ in range(n_recipients)],
        recipient_weights=weights,
    )


def normal_hour(user: User) -> float:
    return float(rng.normal(user.usual_hour, 2.0))


def add_normal_events(user: User) -> None:
    months = [datetime(2026, m, 1, tzinfo=KST) for m in (7, 8, 9)]
    has_rent = rng.random() < 0.5
    rent = round_won(rng.uniform(350_000, 900_000), 10_000)
    rent_day = int(rng.integers(1, 6))
    landlord = user.recipients[0]
    monthly_rate = rng.uniform(3, 15)
    device_change_at = START + timedelta(days=float(rng.uniform(0, 92))) if rng.random() < 0.04 else None

    for month in months:
        user.events.append(Event(at_kst(month.replace(day=user.payday), 9), "salary", user.salary))
        if has_rent:
            user.events.append(
                Event(at_kst(month.replace(day=rent_day), normal_hour(user)), "transfer", rent, landlord)
            )
        for _ in range(rng.poisson(monthly_rate)):
            day = month + timedelta(days=float(rng.integers(0, 28)))
            amount = round_won(np.exp(rng.normal(np.log(50_000), 1.0)))
            if rng.random() < 0.85:
                to = str(rng.choice(user.recipients, p=user.recipient_weights))
            else:
                to = new_account_num()  # 가끔 처음 보내는 계좌 (중고거래, 더치페이)
            user.events.append(
                Event(at_kst(day, normal_hour(user)), "transfer", amount, to,
                      voice=rng.random() < user.voice_prob,
                      attempts=int(rng.random() < 0.05),
                      keywords=int(rng.random() < 0.003))  # 일상 대화에 우연히 키워드
            )

    # 정상이지만 위험해 보이는 거래: 전세 보증금·중고차 등 처음 보내는 계좌로 고액
    if rng.random() < 0.12:
        day = START + timedelta(days=float(rng.uniform(0, 90)))
        user.events.append(
            Event(at_kst(day, rng.normal(13, 2)), "transfer",
                  round_won(rng.uniform(1_000_000, 8_000_000), 100_000), new_account_num())
        )

    user.events.sort(key=lambda e: e.at)
    if device_change_at is not None:  # 휴대폰 교체: 교체 후 첫 이체만 새 기기
        for event in user.events:
            if event.kind == "transfer" and event.at >= device_change_at:
                event.new_device = True
                break


def add_fraud_case(user: User) -> None:
    day = START + timedelta(days=float(rng.uniform(0, 91)))
    target = new_account_num()
    scenario = rng.choice(["account_takeover", "voice_phishing", "test_then_large"], p=[0.4, 0.4, 0.2])

    if scenario == "account_takeover":
        hour = rng.uniform(0, 5) if rng.random() < 0.5 else rng.uniform(0, 24)
        user.events.append(Event(at_kst(day, hour), "transfer", 0, target, 1, "account_takeover",
                                 new_device=rng.random() < 0.9, attempts=int(rng.integers(0, 2)),
                                 drain_ratio=float(rng.uniform(0.85, 1.0))))
    elif scenario == "voice_phishing":
        hour = rng.choice([rng.uniform(22, 29), rng.uniform(9, 18)], p=[0.6, 0.4])
        keywords = int(rng.poisson(1.5)) if rng.random() < 0.7 else 0
        user.events.append(Event(at_kst(day, hour), "transfer", 0, target, 1, "voice_phishing",
                                 voice=rng.random() < 0.6, attempts=int(rng.integers(0, 4)),
                                 rejected=int(rng.random() < 0.2), keywords=keywords,
                                 drain_ratio=float(rng.uniform(0.5, 1.0))))
    else:
        at = at_kst(day, rng.uniform(0, 24))
        user.events.append(Event(at, "transfer", round_won(rng.uniform(1_000, 10_000)), target, 1,
                                 "test_then_large", new_device=rng.random() < 0.5))
        user.events.append(Event(at + timedelta(minutes=float(rng.uniform(2, 30))), "transfer", 0, target, 1,
                                 "test_then_large", new_device=False, attempts=1,
                                 drain_ratio=float(rng.uniform(0.5, 0.95))))
    user.events.sort(key=lambda e: e.at)


def simulate(user: User) -> list[dict]:
    rows, past = [], []
    registered = set(user.recipients)
    for event in user.events:
        if event.kind == "salary":
            user.balance += event.amount
            continue
        amount = event.amount
        if event.drain_ratio is not None:
            amount = round_won(user.balance * event.drain_ratio, 10_000)
            if amount > user.balance:
                amount = user.balance
        if amount <= 0 or amount > user.balance:
            continue  # 잔액 부족한 정상 이체는 일어나지 않은 것으로 본다

        at = event.at.astimezone(timezone.utc)
        ctx = TransferContext(
            at=at,
            amount=amount,
            to_account=event.to_account,
            balance=user.balance,
            user_created_at=user.created_at,
            past_transfers=[p for p in past if p.at >= at - timedelta(days=30)],
            registered_recipients=registered,
            is_new_device=event.new_device,
            input_mode="voice" if event.voice else "text",
            session_attempt_count=event.attempts,
            session_rejected_count=event.rejected,
            session_keyword_count=event.keywords,
        )
        rows.append({
            **compute_features(ctx),
            "label": event.label,
            "scenario": event.scenario,
            "user_id": user.user_id,
            "at": at,
        })
        user.balance -= amount
        past.append(PastTransfer(at, amount, event.to_account))
    return rows


def main() -> None:
    users = [make_user(i) for i in range(N_USERS)]
    for user in users:
        add_normal_events(user)
    for user_index in rng.choice(N_USERS, size=N_FRAUD_CASES, replace=True):
        add_fraud_case(users[user_index])

    df = pd.DataFrame([row for user in users for row in simulate(user)])
    df = df[(df["at"] >= START) & (df["at"] < END)].sort_values("at").reset_index(drop=True)
    df["split"] = np.where(df["at"] < VALID_FROM, "train", "valid")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_DIR / "transactions.parquet", index=False)
    for split in ("train", "valid"):
        df[df["split"] == split].to_parquet(OUT_DIR / f"{split}.parquet", index=False)

    print(f"전체 {len(df):,}건, 사기 {df['label'].sum():,}건 ({df['label'].mean():.2%})")
    print(df.groupby(["split", "scenario"]).size().unstack(fill_value=0))
    assert list(df.columns[: len(FEATURE_NAMES)]) == FEATURE_NAMES


if __name__ == "__main__":
    main()
