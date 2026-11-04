"""화자 임베딩 (SpeechBrain ECAPA-TDNN). PyTorch가 필요해서 `voice` 의존성 그룹으로 따로 설치한다.

    uv sync --group voice

설치돼 있지 않으면 available()이 False이고, 음성 승인 API는 503을 돌려준다 (버튼 + PIN 승인은 그대로 동작).
모델(약 85MB)은 처음 쓸 때 HuggingFace에서 .models/에 받는다.
"""

import logging
import threading
from pathlib import Path

import numpy as np

from avengers_bank.core.exceptions import ApiException

logger = logging.getLogger(__name__)

MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
MODEL_VERSION = "speechbrain/spkrec-ecapa-voxceleb@1"
MODEL_DIR = Path(__file__).resolve().parents[4] / ".models" / "spkrec-ecapa-voxceleb"


class VoiceUnavailableException(ApiException):
    def __init__(self, message: str = "지금은 음성 승인을 쓸 수 없어요. 승인 버튼과 PIN으로 진행해 주세요."):
        super().__init__(status_code=503, code="VOICE_UNAVAILABLE", message=message)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


class SpeakerEncoder:
    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        try:
            import speechbrain  # noqa: F401
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        with self._lock:
            if self._model is None:
                if not self.available():
                    raise VoiceUnavailableException("서버에 화자 인증 모델이 설치되지 않았어요 (uv sync --group voice).")
                from speechbrain.inference.speaker import EncoderClassifier
                from speechbrain.utils.fetching import LocalStrategy

                # Windows는 심볼릭 링크 권한이 없을 수 있어 파일을 복사해서 둔다
                self._model = EncoderClassifier.from_hparams(
                    source=MODEL_SOURCE, savedir=str(MODEL_DIR), run_opts={"device": "cpu"},
                    local_strategy=LocalStrategy.COPY,
                )
                logger.info("화자 인증 모델을 읽었습니다: %s", MODEL_SOURCE)
            return self._model

    def embed(self, samples: np.ndarray) -> np.ndarray:
        """16kHz 음성 → 길이 1로 정규화한 192차원 벡터. CPU에서 약 0.1초 (스레드에서 호출)."""
        import torch

        model = self._load()
        with torch.inference_mode():
            vector = model.encode_batch(torch.from_numpy(samples).unsqueeze(0)).squeeze().numpy()
        return (vector / np.linalg.norm(vector)).astype(np.float32)


speaker_encoder = SpeakerEncoder()
