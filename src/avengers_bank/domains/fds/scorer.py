"""FDS 2단계: LightGBM 위험 점수.

모델은 fds_training/train.py가 만든 fds_training/model/lgbm.txt를 앱에서 한 번만 읽는다.
모델 파일이 없으면 점수 없이(규칙만으로) 동작한다.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np

from avengers_bank.domains.fds.features import FEATURE_LABELS, FEATURE_NAMES, to_vector

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parents[4] / "fds_training" / "model"
TOP_FACTORS = 3


@dataclass(frozen=True)
class Factor:
    feature: str
    label: str
    contribution: float  # SHAP 값 (log-odds). 양수일수록 위험 쪽으로 밀었다


@dataclass(frozen=True)
class Score:
    value: float
    top_factors: list[Factor]


class FdsScorer:
    def __init__(self) -> None:
        self._booster: lgb.Booster | None = None
        self._loaded = False
        self.medium_threshold, self.high_threshold = 0.3, 0.7

    def load(self, model_dir: Path = MODEL_DIR) -> None:
        self._loaded = True
        model_path = model_dir / "lgbm.txt"
        if not model_path.exists():
            logger.warning("FDS 모델 파일이 없어 규칙 엔진만 사용합니다: %s", model_path)
            return
        # Booster(model_file=...)는 Windows 한글 경로를 못 연다 → 문자열로 읽어서 넘긴다
        booster = lgb.Booster(model_str=model_path.read_text(encoding="utf-8"))
        if booster.feature_name() != FEATURE_NAMES:
            raise RuntimeError("FDS 모델의 피처 목록이 features.FEATURE_NAMES와 다릅니다. 다시 학습하세요.")
        thresholds = json.loads((model_dir / "thresholds.json").read_text(encoding="utf-8"))
        self.medium_threshold, self.high_threshold = thresholds["medium"], thresholds["high"]
        self._booster = booster

    def score(self, features: dict[str, float]) -> Score | None:
        if not self._loaded:
            self.load()
        if self._booster is None:
            return None
        x = np.array([to_vector(features)], dtype=float)
        value = float(self._booster.predict(x)[0])
        contributions = self._booster.predict(x, pred_contrib=True)[0][:-1]  # 마지막 열은 bias
        order = np.argsort(contributions)[::-1][:TOP_FACTORS]
        top = [
            Factor(FEATURE_NAMES[i], FEATURE_LABELS[FEATURE_NAMES[i]], round(float(contributions[i]), 3))
            for i in order
            if contributions[i] > 0
        ]
        return Score(value, top)


fds_scorer = FdsScorer()
