"""이체 MCP 서버: 수취인 관리, 이체 확인 카드 준비, 이체 실행.

이체는 두 단계다. prepare_transfer가 확인 카드와 승인 토큰을 만들고, 사람이 내용을 확인한 뒤
execute_transfer(또는 앱의 POST /transfers)로 실행한다. 실행은 POST /transfers와 같은 서비스를 거친다
(확인 카드 토큰 검사, 잔액·한도, FDS, 음성 승인).

execute_transfer는 확인 카드 토큰만으로는 실행하지 않고 항상 이체 PIN이나 음성 승인 토큰을 요구한다.
외부 AI 클라이언트가 prepare_transfer → execute_transfer를 사람 없이 연달아 부르지 못하게 하기 위해서다.

에이전트는 prepare_transfer, execute_transfer, 수취인 등록·변경·삭제를 LLM에게 주지 않는다 (agents/mcp_client.py).
에이전트의 이체 실행은 지금처럼 사용자가 확인 카드에서 승인할 때 앱이 한다.
수취인을 등록하면 FDS의 "처음 보내는 계좌" 검사를 건너뛰게 되므로, 붙여넣은 글에 속아 등록하는 일을 막기 위해서다.
"""

import uuid


from mcp.types import ToolAnnotations
from pydantic import Field

from avengers_bank.core.exceptions import BadRequestException, NotFoundException
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.chat.amount import format_korean_amount
from avengers_bank.domains.chat.confirmation import create_confirmation_token
from avengers_bank.domains.chat.models import ChatSession
from avengers_bank.domains.chat.repository import chat_repository
from avengers_bank.domains.recipients.schemas import RecipientCreate, RecipientUpdate
from avengers_bank.domains.recipients.service import recipient_service
from avengers_bank.domains.speech import digits
from avengers_bank.domains.speech.service import voice_available, voice_service
from avengers_bank.domains.transfers.schemas import TransferCreate
from avengers_bank.domains.transfers.service import transfer_service
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.service import user_service
from avengers_bank.mcp_servers.common import bank_tool, mask, new_server

READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
MOVES_MONEY = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

server = new_server(
    "avengers-transfers",
    "AvengersBank 이체: 수취인(별칭) 조회·관리, 이체 확인 카드 준비(prepare_transfer), 이체 실행(execute_transfer). "
    "실행 전에 확인 카드 내용을 사용자에게 보여 주고, 사용자가 직접 입력한 이체 PIN으로만 실행한다.",
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
    from_checking_account_id: int = Field(gt=0),
    amount: int = Field(gt=0),
    recipient_nickname: str | None = Field(default=None, max_length=50),
    to_account_num: str | None = Field(default=None, max_length=20),
    session_id: str | None = Field(default=None, min_length=1, max_length=64),
) -> dict:
    """이체 확인 카드 만들기 (실행 아님). recipient_nickname 또는 to_account_num 중 하나.
    카드의 confirmation_token은 이 대화(session_id)의 최신 카드 1장만 유효하다.
    session_id를 비우면 새 대화를 만들고 카드의 session_id로 돌려준다 (외부 MCP 클라이언트용)."""
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

    # 3. 대화: 없으면 새로 만든다 (외부 MCP 클라이언트). 승인 토큰이 이 대화에 묶인다
    new_session = session_id is None
    session_id = session_id or uuid.uuid4().hex

    # 음성 승인: 목소리를 등록했으면 "확인 + 무작위 숫자" (서버가 화자 인증을 못 하면 버튼 + PIN)
    voice_enrolled = await voice_service.is_enrolled(db, user.user_id)
    challenge = digits.new_challenge() if voice_enrolled and voice_available() else None
    token, jti, expires_at = create_confirmation_token(
        user_id=user.user_id, session_id=session_id, from_checking_account_id=account.account_id,
        to_account_num=to_num, amount=amount, voice_challenge=challenge,
    )

    # 4. 이 대화의 최신 카드로 등록 (이전 카드는 무효)
    async with db.begin():
        if new_session:
            session = ChatSession(session_id=session_id, user_id=user.user_id, state={})
            await chat_repository.save(db, session)
        else:
            session = await chat_repository.find_session(db, session_id, for_update=True)
            if session is None or session.user_id != user.user_id:
                raise NotFoundException(code="CHAT_SESSION_NOT_FOUND", message="대화를 찾을 수 없습니다.")
        session.state = {**(session.state or {}), "confirmation_jti": jti}

    who = recipient_nickname or holder
    spoken = format_korean_amount(amount)
    return {
        "type": "transfer_confirmation",
        "session_id": session_id,
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


@bank_tool(server, annotations=MOVES_MONEY)
async def execute_transfer(
    db,
    user,
    session_id: str = Field(min_length=1, max_length=64),
    confirmation_token: str = Field(min_length=1, max_length=2000),
    from_checking_account_id: int = Field(gt=0),
    to_account_num: str = Field(min_length=1, max_length=20),
    amount: int = Field(gt=0),
    pin: str | None = Field(default=None, pattern=r"^\d{6}$", description="사용자가 직접 입력한 이체 PIN 6자리"),
    voice_approval_token: str | None = Field(default=None, max_length=2000, description="POST /voice/approvals에서 받은 토큰"),
    device_fingerprint: str | None = Field(default=None, max_length=128),
) -> dict:
    """이체 실행 (돈이 실제로 움직인다). prepare_transfer 카드의 값과 confirmation_token을 그대로 넣는다.
    사용자가 카드 내용(받는 사람·금액·출금 계좌)을 확인하고 직접 입력한 이체 PIN이나 음성 승인 토큰이 반드시 필요하다.
    FDS가 막으면 error FDS_BLOCKED와 extra(위험 신호·경고 문구)를 돌려준다. 같은 카드로 두 번 실행할 수 없다."""
    if pin is None and voice_approval_token is None:
        raise BadRequestException(
            code="PIN_REQUIRED", message="MCP로 이체하려면 사용자가 직접 입력한 이체 PIN이나 음성 승인이 필요해요."
        )
    if pin is not None:
        async with db.begin():
            account_owner = await user_repository.find_by_id(db, user.user_id)
            if not account_owner.has_pin:
                raise BadRequestException(code="PIN_NOT_SET", message="먼저 앱의 설정에서 이체 PIN을 등록해 주세요.")
            if not await user_service.verify_pin(account_owner, pin):
                raise BadRequestException(code="INVALID_PIN", message="이체 PIN이 올바르지 않습니다.")
    result = await transfer_service.transfer(
        db,
        TransferCreate(
            from_checking_account_id=from_checking_account_id, to_account_num=to_account_num, amount=amount,
            pin=pin, session_id=session_id, confirmation_token=confirmation_token,
            voice_approval_token=voice_approval_token, device_fingerprint=device_fingerprint,
        ),
        user,
    )
    return {**result.model_dump(mode="json"), "from_account_num": mask(result.from_account_num),
            "to_account_num": mask(result.to_account_num)}
