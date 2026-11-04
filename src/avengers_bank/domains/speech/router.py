from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.speech.audio import MAX_BYTES
from avengers_bank.domains.speech.schemas import VoiceApprovalResponse, VoiceProfileDelete, VoiceProfileResponse
from avengers_bank.domains.speech.service import voice_available, voice_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/voice", tags=["voice"], responses=error_responses(401, 422))

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]


async def read_upload(file: UploadFile) -> bytes:
    return await file.read(MAX_BYTES + 1)  # 너무 큰 파일은 audio.read_wav가 거절한다


def to_response(profile) -> VoiceProfileResponse:
    return VoiceProfileResponse(
        enrolled=profile is not None,
        available=voice_available(),
        created_at=profile.created_at if profile else None,
        updated_at=profile.updated_at if profile else None,
    )


@router.get("/profile", response_model=SuccessResponse[VoiceProfileResponse])
async def get_profile(db: Db, current_user: CurrentUser):
    return SuccessResponse[VoiceProfileResponse](data=to_response(await voice_service.get_profile(db, current_user)))


@router.post(
    "/profile",
    response_model=SuccessResponse[VoiceProfileResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400),
)
async def enroll(
    db: Db,
    current_user: CurrentUser,
    password: Annotated[str, Form(max_length=128)],
    consent: Annotated[bool, Form(description="생체정보(목소리 특징) 수집·이용 동의")],
    recordings: Annotated[list[UploadFile], File(description="16kHz 모노 WAV 3개")],
):
    """목소리 등록·재등록. 원본 녹음은 저장하지 않고 화자 임베딩만 암호화해 저장한다."""
    profile = await voice_service.enroll(
        db, current_user, password=password, consent=consent,
        recordings=[await read_upload(f) for f in recordings],
    )
    return SuccessResponse[VoiceProfileResponse](data=to_response(profile), message="목소리를 등록했어요.")


@router.delete("/profile", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(404))
async def delete_profile(data: VoiceProfileDelete, db: Db, current_user: CurrentUser):
    await voice_service.delete(db, current_user, data.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/approvals",
    response_model=SuccessResponse[VoiceApprovalResponse],
    responses=error_responses(400, 404),
)
async def approve(
    db: Db,
    current_user: CurrentUser,
    session_id: Annotated[str, Form(max_length=64)],
    confirmation_token: Annotated[str, Form(max_length=2000)],
    recording: Annotated[UploadFile, File(description="\"확인 + 숫자\"를 말한 16kHz 모노 WAV")],
):
    """확인 카드 음성 승인. 실패하면 400 `VOICE_DIGITS_MISMATCH` / `VOICE_NOT_MATCHED`(extra.remaining_attempts),
    횟수를 다 쓰면 `VOICE_LOCKED`. 서버에서 쓸 수 없으면 503 `VOICE_UNAVAILABLE`.
    성공하면 받은 토큰을 POST /transfers의 voice_approval_token에 넣는다."""
    token = await voice_service.approve(
        db, current_user, session_id=session_id, confirmation_token=confirmation_token,
        recording=await read_upload(recording),
    )
    return SuccessResponse[VoiceApprovalResponse](data=VoiceApprovalResponse(voice_approval_token=token))
