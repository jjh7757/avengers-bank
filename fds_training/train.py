"""FDS LightGBM 학습·평가.

사용법 (avengers_bank 폴더에서, generate_data.py 실행 후):
    uv run --group fds python fds_training/train.py
출력:
    fds_training/model/lgbm.txt         서비스가 읽는 모델
    fds_training/model/thresholds.json  MEDIUM / HIGH 임계값
    fds_training/results.md             평가 결과
    fds_training/results/shap_*.png     SHAP 그림
"""

import json
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import shap  # noqa: E402
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score  # noqa: E402

from avengers_bank.core.clock import KST  # noqa: E402
from avengers_bank.domains.fds.features import FEATURE_LABELS, FEATURE_NAMES  # noqa: E402

ROOT = Path(__file__).resolve().parent
DATA, MODEL_DIR, RESULT_DIR = ROOT / "data", ROOT / "model", ROOT / "results"
EARLY_STOP_FROM = datetime(2026, 8, 18, tzinfo=KST)  # train 안에서 마지막 2주는 early stopping 전용
DEFAULT_THRESHOLDS = (0.3, 0.7)
TARGET_RECALL = 0.9  # MEDIUM 임계값: 검증 사기의 90% 이상을 추가 인증 이상으로 잡는다
TARGET_PRECISION = 0.9  # HIGH 임계값: 차단한 것의 90% 이상이 실제 사기

PARAMS = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 20,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "seed": 42,
    "verbose": -1,
}


def precision_at_recall(y, score, recall_target):
    precision, recall, _ = precision_recall_curve(y, score)
    return float(precision[recall >= recall_target].max())


def pick_thresholds(y, score):
    precision, recall, thresholds = precision_recall_curve(y, score)
    precision, recall = precision[:-1], recall[:-1]  # thresholds와 길이 맞추기
    medium = float(thresholds[recall >= TARGET_RECALL].max())
    candidates = thresholds[(precision >= TARGET_PRECISION) & (thresholds > medium)]
    high = float(candidates.min()) if len(candidates) else max(medium, DEFAULT_THRESHOLDS[1])
    return round(medium, 4), round(high, 4)


def business_metrics(df, score, medium, high):
    fraud, legit = df["label"] == 1, df["label"] == 0
    return {
        "사기 탐지(MEDIUM 이상)": f"{(fraud & (score >= medium)).sum()} / {fraud.sum()}건",
        "사기 차단(HIGH)": f"{(fraud & (score >= high)).sum()}건",
        "놓친 사기 금액": f"{int(df.loc[fraud & (score < medium), 'amount'].sum()):,}원",
        "정상 거래 추가 인증(오탐)": f"{(legit & (score >= medium) & (score < high)).sum()} / {legit.sum():,}건",
        "정상 거래 차단(오탐)": f"{(legit & (score >= high)).sum()}건",
    }


def rule_flags(df):
    """rules.py의 MEDIUM 규칙을 피처 컬럼으로 근사한다 (한도·재시도 규칙은 데이터에 없음)."""
    flags = pd.DataFrame({
        "NEW_RECIPIENT_HIGH_AMOUNT": (df["is_new_recipient"] == 1) & (df["amount"] >= 1_000_000),
        "NIGHT_HIGH_AMOUNT": (df["hour"] < 6) & (df["amount"] >= 500_000),
        "NEW_DEVICE": df["is_new_device"] == 1,
        "BALANCE_DRAIN": df["amount_to_balance"] >= 0.9,
        "CONVERSATION_KEYWORD": df["session_keyword_count"] > 0,
    })
    return flags.any(axis=1), flags.sum(axis=1) >= 3


def table(rows: dict[str, dict]) -> str:
    columns = list(next(iter(rows.values())).keys())
    lines = ["| | " + " | ".join(columns) + " |", "|---" * (len(columns) + 1) + "|"]
    lines += [f"| {name} | " + " | ".join(str(v) for v in row.values()) + " |" for name, row in rows.items()]
    return "\n".join(lines)


def main() -> None:
    train_all = pd.read_parquet(DATA / "train.parquet")
    valid = pd.read_parquet(DATA / "valid.parquet")
    fit = train_all[train_all["at"] < EARLY_STOP_FROM]
    stop = train_all[train_all["at"] >= EARLY_STOP_FROM]

    pos = fit["label"].sum()
    params = {**PARAMS, "scale_pos_weight": (len(fit) - pos) / pos}
    booster = lgb.train(
        params,
        lgb.Dataset(fit[FEATURE_NAMES], fit["label"]),
        num_boost_round=2000,
        valid_sets=[lgb.Dataset(stop[FEATURE_NAMES], stop["label"])],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )

    score = booster.predict(valid[FEATURE_NAMES], num_iteration=booster.best_iteration)
    y = valid["label"].to_numpy()
    medium, high = pick_thresholds(y, score)

    MODEL_DIR.mkdir(exist_ok=True)
    RESULT_DIR.mkdir(exist_ok=True)
    # save_model(path)은 Windows에서 한글 경로를 못 연다 → 문자열로 받아 Python이 쓴다
    (MODEL_DIR / "lgbm.txt").write_text(
        booster.model_to_string(num_iteration=booster.best_iteration), encoding="utf-8"
    )
    (MODEL_DIR / "thresholds.json").write_text(
        json.dumps(
            {
                "medium": DEFAULT_THRESHOLDS[0],
                "high": DEFAULT_THRESHOLDS[1],
                "tuned_medium": medium,
                "tuned_high": high,
                "feature_names": FEATURE_NAMES,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # SHAP: 검증 데이터 전체(사기 + 정상)에 대한 피처 기여도
    explainer = shap.TreeExplainer(booster)
    shap_values = explainer.shap_values(valid[FEATURE_NAMES])
    for kind in ("dot", "bar"):
        plt.figure()
        shap.summary_plot(shap_values, valid[FEATURE_NAMES], plot_type=kind, show=False, max_display=15)
        plt.tight_layout()
        plt.savefig(RESULT_DIR / f"shap_summary_{kind}.png", dpi=120)
        plt.close("all")
    mean_abs = pd.Series(np.abs(shap_values).mean(axis=0), index=FEATURE_NAMES).sort_values(ascending=False)

    rules_any, rules_high = rule_flags(valid)
    ml_medium = score >= medium
    comparison = {}
    for name, flagged in {
        "규칙만 (MEDIUM 규칙 1개 이상)": rules_any,
        f"ML만 (점수 ≥ {medium})": ml_medium,
        "규칙 + ML (둘 중 하나)": rules_any | ml_medium,
    }.items():
        flagged = np.asarray(flagged)
        comparison[name] = {
            "사기 탐지": f"{(flagged & (y == 1)).sum()} / {(y == 1).sum()}",
            "정상 오탐": f"{(flagged & (y == 0)).sum()} / {(y == 0).sum():,}",
        }

    by_scenario = {}
    for scenario, group in valid[valid["label"] == 1].groupby("scenario"):
        s = booster.predict(group[FEATURE_NAMES], num_iteration=booster.best_iteration)
        by_scenario[scenario] = {
            "건수": len(group),
            "MEDIUM 이상": int((s >= medium).sum()),
            "HIGH": int((s >= high).sum()),
            "점수 중앙값": f"{np.median(s):.3f}",
        }

    report = f"""# FDS 모델 평가 결과

`fds_training/train.py`가 자동으로 쓰는 파일입니다. 다시 학습하면 덮어씁니다.

## 데이터

| 구분 | 기간 | 거래 | 사기 |
|---|---|---|---|
| 학습 | 2026-07-01 ~ 08-17 | {len(fit):,} | {int(fit['label'].sum())} |
| early stopping | 2026-08-18 ~ 08-31 | {len(stop):,} | {int(stop['label'].sum())} |
| 검증 | 2026-09 | {len(valid):,} | {int(valid['label'].sum())} |

합성 데이터(`generate_data.py`, seed {42})이며 실제 사기 데이터가 아닙니다. 수치는 시나리오 설계에 따라 크게 달라집니다.

## 모델 지표 (검증 데이터)

| 지표 | 값 |
|---|---|
| PR-AUC (주 지표) | {average_precision_score(y, score):.4f} |
| ROC-AUC | {roc_auc_score(y, score):.4f} |
| 재현율 80%에서의 정밀도 | {precision_at_recall(y, score, 0.8):.4f} |
| 트리 수 (early stopping) | {booster.best_iteration} |

## 임계값

- 초기값: LOW < {DEFAULT_THRESHOLDS[0]} ≤ MEDIUM < {DEFAULT_THRESHOLDS[1]} ≤ HIGH
- 조정값: MEDIUM ≥ **{medium}** (검증 사기 재현율 {TARGET_RECALL:.0%} 이상이 되는 가장 큰 값), HIGH ≥ **{high}** (정밀도 {TARGET_PRECISION:.0%} 이상이 되는 가장 작은 값)
- **서비스는 초기값을 씁니다** (`model/thresholds.json`의 `medium`, `high`). 조정값은 `scale_pos_weight` 때문에 점수가 0·1 쪽으로 몰려
  MEDIUM 구간이 거의 사라지고, 같은 검증 데이터(사기 {int(valid['label'].sum())}건)로 고른 값이라 과적합 위험이 큽니다. 아래 표처럼 초기값과 차이도 작습니다.
- 합성 데이터라 점수가 실제보다 훨씬 잘 나옵니다. 모델이 놓치는 경우를 대비해 규칙 엔진이 1차 방어를 맡습니다 (MEDIUM 규칙 3개 이상이면 HIGH).

{table({"초기값 (0.3 / 0.7)": business_metrics(valid, score, *DEFAULT_THRESHOLDS), f"조정값 ({medium} / {high})": business_metrics(valid, score, medium, high)})}

## 시나리오별 탐지 (조정 임계값 기준)

{table(by_scenario)}

## 규칙 엔진과 비교

규칙은 피처 컬럼으로 근사했습니다 (1회·1일 한도, 차단 후 재시도 규칙은 합성 데이터에 없음).

{table(comparison)}

## 피처 중요도 (평균 |SHAP|)

| 피처 | 설명 | 평균 \\|SHAP\\| |
|---|---|---|
""" + "\n".join(f"| `{name}` | {FEATURE_LABELS[name]} | {value:.3f} |" for name, value in mean_abs.head(12).items()) + """

![SHAP summary](results/shap_summary_dot.png)

## 해석할 때 주의할 점

- `weekday`(요일)가 상위에 있지만 생성기는 요일별 차이를 만들지 않았습니다. 사기 표본이 적어서 생긴 우연한 패턴(과적합)으로 봅니다.
- `session_attempt_count`는 생성기에서 사기 시나리오에 일부러 높게 넣은 값이라 중요도가 높게 나옵니다. 실제 데이터에서는 달라질 수 있습니다.
"""
    (ROOT / "results.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
