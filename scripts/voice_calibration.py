"""화자 인증 기준값(VOICE_SIMILARITY_THRESHOLD) 정하기.

여러 사람의 녹음으로 "본인인데 거부되는 비율"과 "남인데 통과되는 비율"을 기준값별로 보여 준다.

녹음 준비: 한 폴더에 `이름_번호.wav`로 모은다 (예: kim_1.wav … kim_6.wav, lee_1.wav …).
- 사람마다 6개 이상: 앞 3개는 등록용(아무 문장), 나머지는 승인용("확인 사칠이"처럼 짧게)
- 조용한 곳과 시끄러운 곳, 휴대폰 마이크와 노트북 마이크를 섞으면 실제에 가깝다
- WAV면 샘플레이트·채널은 상관없다 (16kHz 모노로 바꿔서 쓴다). 녹음 앱 결과가 m4a면 WAV로 변환해 둔다

사용법 (avengers_bank 폴더에서):
    uv run --group voice python scripts/voice_calibration.py 녹음폴더
"""

import sys
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np

from avengers_bank.domains.speech.speaker import cosine, speaker_encoder

ENROLL = 3


def load(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise SystemExit(f"{path.name}: 16bit PCM WAV만 지원합니다.")
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        x = np.interp(np.arange(0, len(x), rate / 16000), np.arange(len(x)), x).astype(np.float32)
    return x


def main(folder: Path) -> None:
    files = defaultdict(list)
    for path in sorted(folder.glob("*.wav")):
        files[path.stem.rsplit("_", 1)[0]].append(path)
    people = {name: paths for name, paths in files.items() if len(paths) > ENROLL}
    if len(people) < 2:
        raise SystemExit("녹음이 4개 이상인 사람이 2명 이상 필요합니다.")

    profiles, trials = {}, {}
    for name, paths in people.items():
        vectors = [speaker_encoder.embed(load(p)) for p in paths]
        mean = np.mean(vectors[:ENROLL], axis=0)
        profiles[name] = mean / np.linalg.norm(mean)
        trials[name] = vectors[ENROLL:]

    same = [cosine(v, profiles[n]) for n, vs in trials.items() for v in vs]
    diff = [cosine(v, profiles[p]) for n, vs in trials.items() for v in vs for p in profiles if p != n]
    print(f"사람 {len(people)}명, 본인 시도 {len(same)}건, 타인 시도 {len(diff)}건")
    print(f"본인 유사도: 최소 {min(same):.3f} / 평균 {np.mean(same):.3f}")
    print(f"타인 유사도: 최대 {max(diff):.3f} / 평균 {np.mean(diff):.3f}\n")

    print("기준값  본인 거부율  타인 통과율")
    for threshold in np.arange(0.20, 0.75, 0.05):
        frr = np.mean(np.array(same) < threshold)
        far = np.mean(np.array(diff) >= threshold)
        print(f" {threshold:.2f}     {frr:6.1%}      {far:6.1%}")
    print("\n타인 통과율을 0에 가깝게 두는 가장 낮은 값을 고르세요. 본인 거부는 버튼 + PIN으로 넘어가므로 불편할 뿐이지만,")
    print("타인 통과는 남이 대신 승인하는 것이다. 정한 값은 .env의 VOICE_SIMILARITY_THRESHOLD에 넣는다.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
