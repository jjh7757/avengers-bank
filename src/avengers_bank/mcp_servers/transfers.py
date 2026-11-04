"""이체 MCP 서버: 수취인 관리, 이체 확인 카드 준비.

이체를 "실행"하는 도구는 없다. prepare_transfer는 확인 카드와 승인 토큰만 만들고,
실행은 사용자가 카드에서 승인했을 때 앱이 POST /transfers로 한다 (FDS·음성 승인·PIN 포함).

에이전트는 prepare_transfer와 수취인 등록·변경·삭제를 LLM에게 주지 않는다 (agents/mcp_client.py).
수취인을 등록하면 FDS의 "처음 보내는 계좌" 검사를 건너뛰게 되므로, 붙여넣은 글에 속아 등록하는 일을 막기 위해서다.
"""

from mcp.types import ToolAnnotations
from pydantic import Field

from avengers_bank.core.exceptions import BadRequestException, NotFoundException
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.chat.amount import format_korean_amount
from avengers_bank.domains.chat.confirmation import create_confirmation_token
from avengers_bank.domains.chat.repository import chat_repository
from avengers_bank.domains.recipients.schemas import RecipientCreate, RecipientUpdate
from avengers_bank.domains.recipients.service import recipient_service
from avengers_bank.domains.speech import digits
from avengers_bank.domains.speech.service import voice_available, voice_service
from avengers_bank.mcp_servers.common import bank_tool, mask, new_server

READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

server = new_server(
    "avengers-transfers",
    "AvengersBank 이체: 수취인(별칭) 조회·관리, 이체 확인 카드 준비. 이체 실행 도구는 없다 (사용자가 앱의 확인 카드에서 승인).",
)


def recipient_json(r) -> dict:
    return {"recipient_id": r.recipient_id, "nickname": r.nickname, "holder_name": r.holder_name,
            "account_num": mask(r.account_num), "last_sent_at": r.last_sent_at.isoformat() if r.last_sent_at else None}


@bank_tool(server, annotations=READ)
async def list_recipients(db, user) -> dict:
    """등록한 수취인 목록 (최근 보낸 순)"""
    return {"recipients": [recipient_json(r) for r in await recipient_service.get_my_recipients(db, user)]}


@bank_tool(server, annotations=READ)
async def find_recipient(db, user, nickname: str = Field(min_length=1, max_length=50)) -> dict:
    """별칭으로 수취인 찾기 ("엄마"). 없으면 error RECIPIENT_NOT_FOUND"""
    return recipient_json(await recipient_service.find_by_nickname(db, user, nickname))


@bank_tool(server, annotations=READ)
async def find_account_holder(db, user, account_num: str = Field(min_length=1, max_length=20)) -> dict:
    """입출금 계좌번호의 예금주 이름 (사용자가 계좌번호를 직접 말했을 때 확인용)"""
    return {"account_num": mask(account_num), "holder_name": await account_service.find_checking_holder(db, account_num)}


@bank_tool(server, annotations=WRITE)
async def register_recipient(
    db, user, account_num: str = Field(min_length=1, max_length=20), nickname: str = Field(min_length=1, max_length=50)
) -> dict:
    """수취인 등록 (앱 화면·외부 클라이언트용. 에이전트 LLM에는 주지 않음)"""
    return recipient_json(await recipient_service.create(db, RecipientCreate(account_num=account_num, nickname=nickname), user))


@bank_tool(server, annotations=WRITE)
async def rename_recipient(db, user, recipient_id: int, nickname: str = Field(min_length=1, max_length=50)) -> dict:
    """수취인 별칭 변경 (에이전트 LLM에는 주지 않음)"""
    return recipient_json(await recipient_service.update(db, recipient_id, RecipientUpdate(nickname=nickname), user))


@bank_tool(server, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
async def delete_recipient(db, user, recipient_id: int) -> dict:
    """수취인 삭제 (에이전트 LLM에는 주지 않음)"""
    await recipient_service.delete(db, recipient_id, user)
    return {"deleted": recipient_id}


@bank_tool(server, annotations=WRITE)
async def prepare_transfer(
    db,
    user,
    session_id: str = Field(min_length=1, max_length=64),
    from_checking_account_id: int = Field(gt=0),
    amount: int = Field(gt=0),
    recipient_nickname: str | None = Field(default=None, max_length=50),
    to_account_num: str | None = Field(default=None, max_length=20),
) -> dict:
    """이체 확인 카드 만들기 (실행 아님). recipient_nickname 또는 to_account_num 중 하나.
    카드의 confirmation_token은 이 대화(session_id)의 최신 카드 1장만 유효하다."""
    # 1. 받는 사람
    if recipient_nickname:
        recipient = await recipient_service.find_by_nickname(db, user, recipient_nickname)
        to_num, holder = recipient.account_num, recipient.holder_name
    elif to_account_num:
        to_num, holder = to_account_num, await account_service.find_checking_holder(db, to_account_num)
    else:
        raise BadRequestException(code="RECIPIENT_REQUIRED", message="받는 사람을 알려 주세요.")

    # 2. 출금 계좌 (본인 입출금 계좌)
    account = await account_service.get_account(db, "checking", from_checking_account_id, user)
    if account.account_num == to_num:
        raise BadRequestException(code="SAME_ACCOUNT", message="같은 계좌로는 이체할 수 없습니다.")

    # 3. 음성 승인: 목소리를 등록했으면 "확인 + 무작위 숫자" (서버가 화자 인증을 못 하면 버튼 + PIN)
    voice_enrolled = await voice_service.is_enrolled(db, user.user_id)
    challenge = digits.new_challenge() if voice_enrolled and voice_available() else None
    token, jti, expires_at = create_confirmation_token(
        user_id=user.user_id, session_id=session_id, from_checking_account_id=account.account_id,
        to_account_num=to_num, amount=amount, voice_challenge=challenge,
    )

    # 4. 이 대화의 최신 카드로 등록 (이전 카드는 무효)
    async with db.begin():
        session = await chat_repository.find_session(db, session_id, for_update=True)
        if session is None or session.user_id != user.user_id:
            raise NotFoundException(code="CHAT_SESSION_NOT_FOUND", message="대화를 찾을 수 없습니다.")
        session.state = {**(session.state or {}), "confirmation_jti": jti}

    who = recipient_nickname or holder
    spoken = format_korean_amount(amount)
    return {
        "type": "transfer_confirmation",
        "from_checking_account_id": account.account_id,
        "from_account_num": account.account_num,
        "from_nickname": account.nickname,
        "from_balance": account.balance,
        "to_account_num": to_num,
        "holder_name": holder,
        "recipient_nickname": recipient_nickname,
        "amount": amount,
        "amount_text": spoken,
        "insufficient_balance": account.balance < amount,
        "confirmation_token": token,
        "confirmation_jti": jti,
        "expires_at": expires_at.isoformat(),
        "voice_enrolled": voice_enrolled,  # true면 버튼으로 승인할 때 PIN이 필요하다
        "voice_challenge": challenge,  # "472"
        "voice_challenge_text": digits.spoken(challenge) if challenge else None,  # "사 칠 이"
        # 확인 카드는 핵심만 읽는다. 계좌번호는 읽지 않는다.
        "tts_text": (
            f"{who}님께 {spoken}을 보냅니다. 승인하시려면 확인, {digits.spoken(challenge)}, 라고 말씀해 주세요."
            if challenge else f"{who}님께 {spoken}을 보냅니다. 승인하시겠어요?"
        ),
    }
