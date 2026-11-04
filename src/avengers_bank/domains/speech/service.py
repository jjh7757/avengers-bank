"""목소리 등록과 음성 승인 (PROJECT_PLAN.md 3.5 "음성 승인 (화자 인증)").

음성 승인 = ① 녹음 속 숫자가 확인 카드의 무작위 숫자와 같고 ② 등록한 목소리와 유사도가 기준 이상.
카드 하나당 voice_max_attempts번 실패하면 그 카드는 버튼 + PIN으로만 승인할 수 있다.
화자 인증은 "다른 사람이 내 폰으로 승인"을 막는다. 보이스피싱에 속은 본인의 승인은 막지 못하며 그건 FDS가 맡는다.
"""

import asyncio
import logging

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.clock import now_utc
from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException, BadRequestException, NotFoundException, UnauthorizedException
from avengers_bank.core.security import verify_password
from avengers_bank.domains.chat.confirmation import decode_confirmation_token
from avengers_bank.domains.chat.repository import chat_repository
from avengers_bank.domains.speech import digits
from avengers_bank.domains.speech.approval import create_voice_approval_token
from avengers_bank.domains.speech.audio import read_wav
from avengers_bank.domains.speech.crypto import decrypt_embedding, encrypt_embedding, encryption_configured
from avengers_bank.domains.speech.models import VoiceProfile
from avengers_bank.domains.speech.repository import voice_repository
from avengers_bank.domains.speech.speaker import MODEL_VERSION, VoiceUnavailableException, cosine, speaker_encoder
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import UserResponse

logger = logging.getLogger(__name__)

ENROLL_RECORDINGS = 3
RECOGNIZE_TIMEOUT_SECONDS = 15  # 승인 단계에서 오래 기다리게 하지 않는다. 넘으면 버튼 + PIN으로


def voice_available() -> bool:
    return encryption_configured() and speaker_encoder.available()


class VoiceService:
    async def get_profile(self, db: AsyncSession, current_user: UserResponse) -> VoiceProfile | None:
        async with db.begin():
            return await voice_repository.find(db, current_user.user_id)

    async def is_enrolled(self, db: AsyncSession, user_id: int) -> bool:
        async with db.begin():
            return await voice_repository.find(db, user_id) is not None

    async def enroll(
        self, db: AsyncSession, current_user: UserResponse, *, password: str, consent: bool, recordings: list[bytes]
    ) -> VoiceProfile:
        """등록·재등록. 다른 사람이 자기 목소리로 바꿔치기하지 못하도록 비밀번호를 다시 확인한다."""
        if not consent:
            raise BadRequestException(code="CONSENT_REQUIRED", message="생체정보 수집·이용에 동의해야 등록할 수 있어요.")
        if len(recordings) != ENROLL_RECORDINGS:
            raise BadRequestException(code="INVALID_AUDIO", message=f"문장 {ENROLL_RECORDINGS}개를 모두 녹음해 주세요.")
        if not voice_available():
            raise VoiceUnavailableException()
        await self._check_password(db, current_user.user_id, password)

        samples = [read_wav(data) for data in recordings]
        vectors = [await run_in_threadpool(speaker_encoder.embed, s) for s in samples]
        mean = np.mean(vectors, axis=0)
        embedding = mean / np.linalg.norm(mean)
        # 원본 녹음(samples)은 여기서 버린다. 저장하는 것은 암호화한 임베딩뿐이다.

        now = now_utc()
        async with db.begin():
            profile = await voice_repository.find(db, current_user.user_id)
            if profile is None:
                profile = VoiceProfile(user_id=current_user.user_id, created_at=now)
            profile.embedding_encrypted = encrypt_embedding(embedding)
            profile.model_version = MODEL_VERSION
            profile.consented_at = now
            profile.updated_at = now
            await voice_repository.save(db, profile)
        return profile

    async def delete(self, db: AsyncSession, current_user: UserResponse, password: str) -> None:
        await self._check_password(db, current_user.user_id, password)
        async with db.begin():
            profile = await voice_repository.find(db, current_user.user_id)
            if profile is None:
                raise NotFoundException(code="VOICE_NOT_ENROLLED", message="등록된 목소리가 없어요.")
            await voice_repository.delete(db, profile)

    async def approve(
        self, db: AsyncSession, current_user: UserResponse, *, session_id: str, confirmation_token: str, recording: bytes
    ) -> str:
        """확인 카드를 목소리로 승인한다. 성공하면 POST /transfers에 넣을 음성 승인 토큰."""
        settings = get_settings()
        if not voice_available():
            raise VoiceUnavailableException()
        samples = read_wav(recording)

        # 1. 카드가 지금 유효한지, 시도 횟수가 남았는지
        async with db.begin():
            confirmation = await self._current_confirmation(db, current_user.user_id, session_id, confirmation_token)
            session = await chat_repository.find_session(db, session_id)
            failures = self._failures(session.state, confirmation.jti)
            if failures >= settings.voice_max_attempts:
                raise BadRequestException(
                    code="VOICE_LOCKED", message="목소리 확인에 여러 번 실패했어요. 승인 버튼과 PIN으로 진행해 주세요.",
                    extra={"remaining_attempts": 0},
                )
            profile = await voice_repository.find(db, current_user.user_id)
            if profile is None:
                raise NotFoundException(code="VOICE_NOT_ENROLLED", message="등록된 목소리가 없어요.")
            enrolled = decrypt_embedding(profile.embedding_encrypted)

        # 2. 숫자(Gemini)와 목소리(ECAPA)를 동시에 확인 (트랜잭션 밖)
        try:
            heard, vector = await asyncio.wait_for(
                asyncio.gather(digits.recognize(recording), run_in_threadpool(speaker_encoder.embed, samples)),
                timeout=RECOGNIZE_TIMEOUT_SECONDS,
            )
        except ApiException:
            raise
        except TimeoutError as exc:
            logger.warning("음성 승인 시간 초과: user=%s", current_user.user_id)
            raise VoiceUnavailableException("목소리 확인이 늦어지고 있어요. 승인 버튼과 PIN으로 진행해 주세요.") from exc
        except Exception as exc:
            logger.exception("음성 승인 처리 실패")
            raise VoiceUnavailableException() from exc
        similarity = cosine(vector, enrolled)
        digits_ok = heard.digits == confirmation.voice_challenge
        voice_ok = similarity >= settings.voice_similarity_threshold
        logger.info("음성 승인 user=%s 숫자=%s 유사도=%.3f 기준=%.2f", current_user.user_id, digits_ok, similarity,
                    settings.voice_similarity_threshold)
        if digits_ok and voice_ok:
            return create_voice_approval_token(current_user.user_id, confirmation.jti)

        # 3. 실패 횟수를 기록하고 나서 알린다 (예외를 트랜잭션 안에서 던지면 기록이 롤백된다)
        async with db.begin():
            session = await chat_repository.find_session(db, session_id, for_update=True)
            failures = self._failures(session.state, confirmation.jti) + 1
            session.state = {**session.state, "voice_failures": {"jti": confirmation.jti, "count": failures}}
        remaining = max(settings.voice_max_attempts - failures, 0)
        if not digits_ok:
            code, message = "VOICE_DIGITS_MISMATCH", f"숫자를 다르게 들었어요. \"확인 {digits.spoken(confirmation.voice_challenge)}\"라고 말씀해 주세요."
        else:
            code, message = "VOICE_NOT_MATCHED", "등록한 목소리와 달라요."
        if remaining == 0:
            message += " 이제 승인 버튼과 PIN으로 진행해 주세요."
        raise BadRequestException(code=code, message=message, extra={"remaining_attempts": remaining})

    async def _current_confirmation(self, db: AsyncSession, user_id: int, session_id: str, token: str):
        confirmation = decode_confirmation_token(token)
        session = await chat_repository.find_session(db, session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundException(code="CHAT_SESSION_NOT_FOUND", message="대화를 찾을 수 없습니다.")
        if confirmation.user_id != user_id or confirmation.session_id != session_id:
            raise BadRequestException(code="CONFIRMATION_MISMATCH", message="확인 카드와 요청 내용이 다릅니다.")
        if (session.state or {}).get("confirmation_jti") != confirmation.jti:
            raise BadRequestException(code="CONFIRMATION_USED", message="이미 처리했거나 바뀐 확인 카드입니다. 다시 요청해 주세요.")
        if not confirmation.voice_challenge:
            raise BadRequestException(code="VOICE_NOT_REQUESTED", message="이 확인 카드는 음성 승인을 쓰지 않아요.")
        return confirmation

    @staticmethod
    def _failures(state: dict | None, jti: str) -> int:
        record = (state or {}).get("voice_failures") or {}
        return record.get("count", 0) if record.get("jti") == jti else 0

    async def _check_password(self, db: AsyncSession, user_id: int, password: str) -> None:
        async with db.begin():
            user = await user_repository.find_by_id(db, user_id)
        if user is None or not await run_in_threadpool(verify_password, password, user.hashed_password):
            raise UnauthorizedException(message="비밀번호가 올바르지 않습니다.", code="INVALID_CREDENTIALS")


voice_service = VoiceService()
