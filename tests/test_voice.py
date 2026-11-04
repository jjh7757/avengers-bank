"""목소리 등록·음성 승인 테스트. 화자 모델과 Gemini 숫자 인식은 가짜로 바꾼다.

가짜 화자 모델은 녹음의 주파수로 목소리를 구분한다: voice=1과 voice=2는 서로 다른 사람.
"""

import io
import wave

import numpy as np
import pytest

from avengers_bank.agents import llm
from avengers_bank.agents.state import Extraction
from avengers_bank.domains.speech import digits
from avengers_bank.domains.speech.digits import Heard
from avengers_bank.domains.speech.speaker import speaker_encoder
from tests.conftest import new_chat_session, open_checking

pytestmark = pytest.mark.anyio
PASSWORD = "password1234"


def make_wav(voice: int = 1, seconds: float = 1.5, amplitude: float = 0.2) -> bytes:
    t = np.arange(int(16000 * seconds)) / 16000
    samples = (amplitude * np.sin(2 * np.pi * (200 + 100 * voice) * t) * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(samples.tobytes())
    return buffer.getvalue()


def fake_embed(samples: np.ndarray) -> np.ndarray:
    vector = np.zeros(192, dtype=np.float32)
    vector[int(np.argmax(np.abs(np.fft.rfft(samples)))) % 192] = 1.0
    return vector


@pytest.fixture(autouse=True)
def fake_voice(monkeypatch):
    """heard.digits로 다음 숫자 인식 결과를 정한다 (None이면 카드의 숫자를 그대로 들은 것으로)."""

    class Heard_:
        digits: str | None = None

    heard = Heard_()
    monkeypatch.setattr(speaker_encoder, "available", lambda: True)
    monkeypatch.setattr(speaker_encoder, "embed", fake_embed)

    async def recognize(wav: bytes) -> Heard:
        return Heard(transcript="확인", digits=heard.digits or heard.expected)

    monkeypatch.setattr(digits, "recognize", recognize)
    return heard


@pytest.fixture(autouse=True)
def fake_classifier(monkeypatch):
    async def classify(history, user_text, pending):
        return Extraction(intent="transfer", recipient="엄마", amount=50_000)

    monkeypatch.setattr(llm, "classify", classify)


@pytest.fixture
async def bank(client, user, other_user):
    mine = await open_checking(client, user, balance=1_000_000)
    mom = await open_checking(client, other_user)
    await client.post("/recipients", headers=user, json={"account_num": mom["account_num"], "nickname": "엄마"})
    await client.put("/users/me/pin", headers=user, json={"password": PASSWORD, "pin": "123456"})
    return {"mine": mine, "session_id": await new_chat_session(client, user)}


async def enroll(client, headers, voice=1, consent=True, password=PASSWORD, count=3):
    return await client.post(
        "/voice/profile",
        headers=headers,
        data={"password": password, "consent": str(consent).lower()},
        files=[("recordings", (f"r{i}.wav", make_wav(voice), "audio/wav")) for i in range(count)],
    )


async def new_card(client, headers, session_id, fake_voice) -> dict:
    response = await client.post(
        f"/chat/sessions/{session_id}/messages", headers=headers, json={"text": "엄마한테 5만원 보내줘"}
    )
    card = response.json()["data"]["assistant_message"]["card"]
    fake_voice.expected = card["voice_challenge"]
    return card


async def voice_approve(client, headers, session_id, card, voice=1):
    return await client.post(
        "/voice/approvals",
        headers=headers,
        data={"session_id": session_id, "confirmation_token": card["confirmation_token"]},
        files={"recording": ("approve.wav", make_wav(voice), "audio/wav")},
    )


def transfer_body(card, session_id, **extra):
    return {
        "from_checking_account_id": card["from_checking_account_id"],
        "to_account_num": card["to_account_num"],
        "amount": card["amount"],
        "session_id": session_id,
        "confirmation_token": card["confirmation_token"],
        **extra,
    }


# ---------- 등록 ----------


async def test_enroll_status_and_delete(client, user):
    response = await client.get("/voice/profile", headers=user)
    assert response.json()["data"] == {"enrolled": False, "available": True, "created_at": None, "updated_at": None}

    response = await enroll(client, user)
    assert response.status_code == 201, response.text
    assert response.json()["data"]["enrolled"] is True

    response = await client.request("DELETE", "/voice/profile", headers=user, json={"password": "wrong-password"})
    assert response.status_code == 401
    response = await client.request("DELETE", "/voice/profile", headers=user, json={"password": PASSWORD})
    assert response.status_code == 204
    assert (await client.get("/voice/profile", headers=user)).json()["data"]["enrolled"] is False


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"consent": False}, 400, "CONSENT_REQUIRED"),
        ({"password": "wrong-password"}, 401, "INVALID_CREDENTIALS"),
        ({"count": 2}, 400, "INVALID_AUDIO"),
    ],
)
async def test_enroll_rejected(client, user, kwargs, status, code):
    response = await enroll(client, user, **kwargs)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_enroll_rejects_silent_or_short_audio(client, user):
    for wav in (make_wav(amplitude=0.0), make_wav(seconds=0.3)):
        response = await client.post(
            "/voice/profile", headers=user, data={"password": PASSWORD, "consent": "true"},
            files=[("recordings", ("r.wav", wav, "audio/wav"))] * 3,
        )
        assert response.json()["error"]["code"] == "INVALID_AUDIO"


async def test_embedding_is_encrypted(client, user):
    from avengers_bank.core.database import SessionLocal
    from avengers_bank.domains.speech.models import VoiceProfile

    await enroll(client, user)
    async with SessionLocal() as db:
        [profile] = (await db.execute(VoiceProfile.__table__.select())).all()
    raw = fake_embed(np.zeros(1)).tobytes()
    assert raw not in profile.embedding_encrypted  # 평문 벡터가 그대로 저장되지 않았다


# ---------- 확인 카드 ----------


async def test_card_without_voice_profile(client, user, bank, fake_voice):
    card = await new_card(client, user, bank["session_id"], fake_voice)
    assert (card["voice_enrolled"], card["voice_challenge"]) == (False, None)
    assert card["tts_text"].endswith("승인하시겠어요?")
    # 목소리 미등록: 지금처럼 버튼만으로 승인
    response = await client.post("/transfers", headers=user, json=transfer_body(card, bank["session_id"]))
    assert response.status_code == 200


async def test_card_with_voice_profile(client, user, bank, fake_voice):
    await enroll(client, user)
    card = await new_card(client, user, bank["session_id"], fake_voice)
    assert card["voice_enrolled"] is True
    challenge = card["voice_challenge"]
    assert len(set(challenge)) == 3 and set(challenge) <= set("23456789")  # 서로 다른 숫자, 0·1 없음
    assert card["voice_challenge_text"] in card["tts_text"]
    assert "확인" in card["tts_text"]


# ---------- 음성 승인 ----------


async def test_voice_approval_then_transfer(client, user, bank, fake_voice):
    await enroll(client, user, voice=1)
    card = await new_card(client, user, bank["session_id"], fake_voice)

    response = await voice_approve(client, user, bank["session_id"], card, voice=1)
    assert response.status_code == 200, response.text
    token = response.json()["data"]["voice_approval_token"]

    response = await client.post(
        "/transfers", headers=user, json=transfer_body(card, bank["session_id"], voice_approval_token=token)
    )
    assert response.status_code == 200, response.text


async def test_button_approval_needs_pin_when_enrolled(client, user, bank, fake_voice):
    await enroll(client, user)
    card = await new_card(client, user, bank["session_id"], fake_voice)

    response = await client.post("/transfers", headers=user, json=transfer_body(card, bank["session_id"]))
    assert response.json()["error"]["code"] == "PIN_REQUIRED"
    assert response.json()["error"]["extra"]["has_pin"] is True

    response = await client.post("/transfers", headers=user, json=transfer_body(card, bank["session_id"], pin="000000"))
    assert response.json()["error"]["code"] == "INVALID_PIN"

    response = await client.post("/transfers", headers=user, json=transfer_body(card, bank["session_id"], pin="123456"))
    assert response.status_code == 200


async def test_failures_lock_voice_approval(client, user, bank, fake_voice):
    await enroll(client, user, voice=1)
    card = await new_card(client, user, bank["session_id"], fake_voice)

    fake_voice.digits = "999"  # 숫자를 틀리게 말함
    response = await voice_approve(client, user, bank["session_id"], card, voice=1)
    error = response.json()["error"]
    assert (error["code"], error["extra"]["remaining_attempts"]) == ("VOICE_DIGITS_MISMATCH", 1)

    fake_voice.digits = None  # 숫자는 맞지만 다른 사람 목소리
    response = await voice_approve(client, user, bank["session_id"], card, voice=2)
    error = response.json()["error"]
    assert (error["code"], error["extra"]["remaining_attempts"]) == ("VOICE_NOT_MATCHED", 0)

    # 본인 목소리로도 더는 안 되고, 버튼 + PIN만 남는다
    response = await voice_approve(client, user, bank["session_id"], card, voice=1)
    assert response.json()["error"]["code"] == "VOICE_LOCKED"
    response = await client.post("/transfers", headers=user, json=transfer_body(card, bank["session_id"], pin="123456"))
    assert response.status_code == 200


async def test_voice_token_is_bound_to_its_card(client, user, bank, fake_voice):
    await enroll(client, user)
    first = await new_card(client, user, bank["session_id"], fake_voice)
    token = (await voice_approve(client, user, bank["session_id"], first)).json()["data"]["voice_approval_token"]

    second = await new_card(client, user, bank["session_id"], fake_voice)
    response = await client.post(
        "/transfers", headers=user, json=transfer_body(second, bank["session_id"], voice_approval_token=token)
    )
    assert response.json()["error"]["code"] == "INVALID_VOICE_APPROVAL"


async def test_old_card_cannot_be_voice_approved(client, user, bank, fake_voice):
    await enroll(client, user)
    old = await new_card(client, user, bank["session_id"], fake_voice)
    await new_card(client, user, bank["session_id"], fake_voice)
    response = await voice_approve(client, user, bank["session_id"], old)
    assert response.json()["error"]["code"] == "CONFIRMATION_USED"


async def test_voice_unavailable_falls_back_to_pin(client, user, bank, fake_voice, monkeypatch):
    await enroll(client, user)
    monkeypatch.setattr(speaker_encoder, "available", lambda: False)  # 서버에 PyTorch가 없는 경우

    card = await new_card(client, user, bank["session_id"], fake_voice)
    assert (card["voice_enrolled"], card["voice_challenge"]) == (True, None)
    response = await client.post(
        "/voice/approvals", headers=user,
        data={"session_id": bank["session_id"], "confirmation_token": card["confirmation_token"]},
        files={"recording": ("a.wav", make_wav(), "audio/wav")},
    )
    assert response.status_code == 503
    response = await client.post("/transfers", headers=user, json=transfer_body(card, bank["session_id"], pin="123456"))
    assert response.status_code == 200
