from datetime import datetime, timedelta, timezone

import pytest

from avengers_bank.core.clock import KST
from avengers_bank.domains.fds.features import (
    FEATURE_NAMES,
    PastTransfer,
    TransferContext,
    compute_features,
    count_keywords,
)
from avengers_bank.domains.fds.rules import RiskLevel, evaluate_rules, rule_level
from avengers_bank.domains.fds.scorer import FdsScorer
from tests.conftest import confirmed, new_chat_session, open_checking

pytestmark = pytest.mark.anyio

DAYTIME = datetime(2026, 11, 4, 14, 0, tzinfo=KST).astimezone(timezone.utc)
MOM = "110-111-111111"
STRANGER = "110-999-999999"


def context(**overrides) -> TransferContext:
    """아무 규칙에도 걸리지 않는 평범한 이체: 낮 2시, 등록된 엄마에게 5만원."""
    base = {
        "at": DAYTIME,
        "amount": 50_000,
        "to_account": MOM,
        "balance": 1_000_000,
        "user_created_at": DAYTIME - timedelta(days=400),
        "registered_recipients": {MOM},
        "per_transfer_limit": 5_000_000,
        "daily_transfer_limit": 10_000_000,
    }
    return TransferContext(**{**base, **overrides})


def codes(ctx: TransferContext) -> set[str]:
    return {hit.code for hit in evaluate_rules(ctx)}


# ---- 규칙 엔진: 규칙별 1건 ----


def test_normal_transfer_hits_no_rule():
    assert codes(context()) == set()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"amount": 5_000_001, "balance": 10_000_000}, "PER_TRANSFER_LIMIT"),
        ({"sent_today": 9_990_000}, "DAILY_LIMIT"),
        ({"to_account": STRANGER, "amount": 1_000_000}, "NEW_RECIPIENT_HIGH_AMOUNT"),
        ({"at": datetime(2026, 11, 4, 2, 0, tzinfo=KST), "amount": 500_000}, "NIGHT_HIGH_AMOUNT"),
        ({"is_new_device": True}, "NEW_DEVICE"),
        ({"amount": 900_000}, "BALANCE_DRAIN"),
        ({"rejected_recently_in_session": True}, "REPEATED_ATTEMPT"),
        ({"session_keyword_count": 1}, "CONVERSATION_KEYWORD"),
    ],
)
def test_each_rule(overrides, expected):
    assert expected in codes(context(**overrides))


def test_rule_boundaries():
    assert "NEW_RECIPIENT_HIGH_AMOUNT" not in codes(context(to_account=STRANGER, amount=999_999))
    assert "NIGHT_HIGH_AMOUNT" not in codes(context(at=datetime(2026, 11, 4, 6, 0, tzinfo=KST), amount=900_000, balance=10_000_000))
    assert "BALANCE_DRAIN" not in codes(context(amount=899_999))


def test_three_medium_rules_escalate_to_high():
    hits = evaluate_rules(context(to_account=STRANGER, amount=1_000_000, is_new_device=True, balance=1_050_000))
    assert {h.code for h in hits} == {"NEW_RECIPIENT_HIGH_AMOUNT", "NEW_DEVICE", "BALANCE_DRAIN"}
    assert rule_level(hits) == RiskLevel.HIGH
    assert rule_level(hits[:2]) == RiskLevel.MEDIUM


def test_count_keywords():
    assert count_keywords(["검찰청인데요, 안전 계좌로 옮기세요"]) == 2
    assert count_keywords(["엄마한테 5만원 보내줘"]) == 0


# ---- 피처 ----


def test_features_use_history():
    past = [
        PastTransfer(DAYTIME - timedelta(days=d, minutes=30), 100_000, MOM) for d in (0, 1, 10, 40)
    ]
    features = compute_features(context(amount=1_000_000, past_transfers=past))
    assert list(features) == FEATURE_NAMES
    assert features["amount_vs_30d_avg"] == pytest.approx(10.0)  # 40일 전 거래는 빠진다
    assert features["transfers_7d"] == 2
    assert features["count_1h"] == 1
    assert features["recipient_send_count"] == 3
    assert features["is_new_recipient"] == 0
    assert features["hour"] == pytest.approx(14.0)
    assert features["hour_diff_from_usual"] < 1


def test_real_model_scores_scenarios():
    """fds_training/model의 실제 모델: 사기 시나리오는 정상 이체보다 점수가 높아야 한다."""
    scorer = FdsScorer()
    scorer.load()
    past = [PastTransfer(DAYTIME - timedelta(days=d), 50_000, MOM) for d in range(1, 20, 3)]
    normal = scorer.score(compute_features(context(past_transfers=past)))
    phishing = scorer.score(compute_features(context(
        at=datetime(2026, 11, 4, 2, 0, tzinfo=KST).astimezone(timezone.utc),
        amount=950_000, to_account=STRANGER, past_transfers=past,
        input_mode="voice", session_keyword_count=2, session_attempt_count=2,
    )))
    assert normal.value < scorer.medium_threshold
    assert phishing.value >= scorer.high_threshold
    assert phishing.top_factors and all(f.contribution > 0 for f in phishing.top_factors)


# ---- 이체 API 연동 ----


async def setup_transfer(client, user, other_user, balance=2_000_000):
    source = await open_checking(client, user, balance=balance)
    target = await open_checking(client, other_user)
    body = {"from_checking_account_id": source["account_id"], "to_account_num": target["account_num"]}
    return source, target, body


async def set_pin(client, headers, pin="123456"):
    response = await client.put("/users/me/pin", headers=headers, json={"password": "password1234", "pin": pin})
    assert response.status_code == 200
    assert response.json()["data"]["has_pin"] is True


async def test_low_passes_and_is_logged(client, user, other_user):
    _, _, body = await setup_transfer(client, user, other_user)
    response = await client.post("/transfers", headers=user, json={**body, "amount": 10_000})
    assert response.status_code == 200
    assert response.json()["data"]["risk_level"] == "LOW"

    [log] = (await client.get("/fds/logs", headers=user)).json()["data"]
    assert (log["risk_level"], log["decision"], log["rule_hits"]) == ("LOW", "PASS", [])


async def test_medium_requires_pin(client, user, other_user):
    source, _, body = await setup_transfer(client, user, other_user)
    body = {**body, "amount": 1_500_000}  # 처음 보내는 계좌로 150만원

    response = await client.post("/transfers", headers=user, json=body)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "ADDITIONAL_AUTH_REQUIRED"
    assert error["extra"]["risk_level"] == "MEDIUM"
    assert error["extra"]["has_pin"] is False
    assert [h["code"] for h in error["extra"]["rule_hits"]] == ["NEW_RECIPIENT_HIGH_AMOUNT"]

    await set_pin(client, user)
    response = await client.post("/transfers", headers=user, json={**body, "pin": "000000"})
    assert response.json()["error"]["code"] == "INVALID_PIN"

    response = await client.post("/transfers", headers=user, json={**body, "pin": "123456"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["risk_level"] == "MEDIUM"

    decisions = [log["decision"] for log in (await client.get("/fds/logs", headers=user)).json()["data"]]
    assert decisions == ["PASS_WITH_AUTH", "AUTH_FAILED", "AUTH_REQUIRED"]


async def test_high_ml_score_blocks_without_moving_money(client, user, other_user, ml_score):
    source, _, body = await setup_transfer(client, user, other_user)
    ml_score.value = 0.95

    response = await client.post("/transfers", headers=user, json={**body, "amount": 10_000, "pin": "123456"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "FDS_BLOCKED"
    assert error["extra"]["risk_level"] == "HIGH"
    assert error["extra"]["ml_score"] == 0.95
    assert "송금을 요구하지 않습니다" in error["extra"]["warning"]

    # 돈은 그대로, 차단 기록은 남는다
    response = await client.get(f"/accounts/checking/{source['account_id']}", headers=user)
    assert response.json()["data"]["balance"] == 2_000_000
    [log] = (await client.get("/fds/logs", headers=user)).json()["data"]
    assert (log["decision"], log["fds_log_id"]) == ("BLOCKED", error["extra"]["fds_log_id"])


async def test_medium_ml_score(client, user, other_user, ml_score):
    _, _, body = await setup_transfer(client, user, other_user)
    ml_score.value = 0.5
    response = await client.post("/transfers", headers=user, json={**body, "amount": 10_000})
    assert response.json()["error"]["code"] == "ADDITIONAL_AUTH_REQUIRED"


async def test_repeated_attempt_after_block(client, user, other_user, ml_score):
    _, _, body = await setup_transfer(client, user, other_user)
    chat_1, chat_2 = await new_chat_session(client, user), await new_chat_session(client, user)

    ml_score.value = 0.95
    response = await client.post("/transfers", headers=user, json=await confirmed({**body, "amount": 1_000_000}, chat_1))
    assert response.json()["error"]["code"] == "FDS_BLOCKED"

    # 같은 세션에서 금액만 바꿔 재시도: 모델 점수가 낮아도 REPEATED_ATTEMPT로 차단
    ml_score.value = 0.01
    response = await client.post("/transfers", headers=user, json=await confirmed({**body, "amount": 90_000}, chat_1))
    error = response.json()["error"]
    assert error["code"] == "FDS_BLOCKED"
    assert "REPEATED_ATTEMPT" in [h["code"] for h in error["extra"]["rule_hits"]]

    # 다른 세션이면 통과
    response = await client.post("/transfers", headers=user, json=await confirmed({**body, "amount": 90_000}, chat_2))
    assert response.status_code == 200


async def test_new_device_after_first_device_registered(client, user, other_user):
    _, _, body = await setup_transfer(client, user, other_user)

    # 첫 기기는 새 기기로 보지 않고, 이체에 성공하면 등록된다
    response = await client.post("/transfers", headers=user, json={**body, "amount": 10_000, "device_fingerprint": "phone-A"})
    assert response.json()["data"]["risk_level"] == "LOW"

    response = await client.post("/transfers", headers=user, json={**body, "amount": 10_000, "device_fingerprint": "phone-A"})
    assert response.json()["data"]["risk_level"] == "LOW"

    response = await client.post("/transfers", headers=user, json={**body, "amount": 10_000, "device_fingerprint": "laptop-B"})
    error = response.json()["error"]
    assert error["code"] == "ADDITIONAL_AUTH_REQUIRED"
    assert [h["code"] for h in error["extra"]["rule_hits"]] == ["NEW_DEVICE"]


async def test_registered_recipient_is_not_new(client, user, other_user):
    _, target, body = await setup_transfer(client, user, other_user, balance=5_000_000)
    await client.post("/recipients", headers=user, json={"account_num": target["account_num"], "nickname": "엄마"})
    response = await client.post("/transfers", headers=user, json={**body, "amount": 1_500_000})
    assert response.status_code == 200


async def test_fds_logs_only_mine(client, user, other_user):
    _, _, body = await setup_transfer(client, user, other_user)
    await client.post("/transfers", headers=user, json={**body, "amount": 10_000})
    response = await client.get("/fds/logs", headers=other_user)
    assert response.json()["data"] == []


async def test_set_pin_wrong_password(client, user):
    response = await client.put("/users/me/pin", headers=user, json={"password": "wrong-password", "pin": "123456"})
    assert response.status_code == 401
    response = await client.put("/users/me/pin", headers=user, json={"password": "password1234", "pin": "12ab56"})
    assert response.status_code == 422
