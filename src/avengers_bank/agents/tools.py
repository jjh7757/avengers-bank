"""에이전트 도구. 모두 기존 도메인 service를 호출하고, 입력은 Pydantic 스키마로 검증한다.

- 조회 도구(build_read_tools): LLM이 골라서 호출한다. 돈을 움직이는 도구는 LLM에게 주지 않는다.
- find_recipient, prepare_transfer: 이체 노드가 코드로 직접 호출한다. prepare_transfer는 확인 카드만 만들고
  실행하지 않는다. 실행은 사용자가 카드에서 승인했을 때 프론트가 POST /transfers로 한다.
"""

import json
from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.accounts.schemas import AccountSummaryResponse
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.cards.service import card_service
from avengers_bank.domains.chat.amount import format_korean_amount
from avengers_bank.domains.chat.confirmation import create_confirmation_token
from avengers_bank.domains.products.schemas import AccountProductResponse, CardProductResponse
from avengers_bank.domains.products.service import product_service
from avengers_bank.domains.recipients.service import recipient_service
from avengers_bank.domains.speech import digits
from avengers_bank.domains.speech.service import voice_available, voice_service
from avengers_bank.domains.users.schemas import UserResponse


@dataclass
class ToolContext:
    db: AsyncSession
    user: UserResponse
    session_id: str


def mask(number: str) -> str:
    """에이전트 답변에는 뒤 4자리만: 110-123-456789 → ****6789"""
    return "****" + number.replace("-", "")[-4:]


def to_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


# ---------- 조회 도구 (LLM용) ----------


class NoArgs(BaseModel):
    pass


class HistoriesArgs(BaseModel):
    account_type: Literal["checking", "deposit", "savings"] = Field(description="계좌 종류")
    account_id: int = Field(description="get_my_accounts 결과의 account_id")
    limit: int = Field(default=10, ge=1, le=30)


class ProductSearchArgs(BaseModel):
    kind: Literal["account", "card", "all"] = Field(default="all", description="계좌 상품 / 카드 상품 / 전체")
    keyword: str | None = Field(default=None, max_length=30, description="이름·설명에서 찾을 단어 (예: 적금, 청년)")


class RecipientArgs(BaseModel):
    nickname: str = Field(min_length=1, max_length=50, description='받는 사람을 부르는 말 (예: "엄마")')


def build_read_tools(ctx: ToolContext) -> list[StructuredTool]:
    async def get_my_accounts() -> str:
        accounts = await account_service.get_my_accounts(ctx.db, ctx.user)
        return to_json([
            {**a.model_dump(include={"account_type", "account_id", "balance", "nickname"}),
             "account_num": mask(a.account_num)}
            for a in accounts
        ])

    async def get_account_histories(account_type: str, account_id: int, limit: int = 10) -> str:
        try:
            histories = await account_service.get_histories(ctx.db, account_type, account_id, ctx.user)
        except ApiException as e:
            return to_json({"error": e.message})
        return to_json([h.model_dump(include={"date", "amount", "type"}) for h in histories[:limit]])

    async def get_my_cards() -> str:
        cards = await card_service.get_my_cards(ctx.db, ctx.user)
        return to_json([
            {"card_type": c.card_type, "card_id": c.card_id, "card_num": mask(c.card_num),
             "accumulated_amount": c.accumulated_amount}
            for c in cards
        ])

    async def search_products(kind: str = "all", keyword: str | None = None) -> str:
        # TODO(6단계 선택): RAG(Chroma)로 상품 설명·약관 검색
        products = []
        if kind in ("account", "all"):
            products += [AccountProductResponse.model_validate(p).model_dump()
                         for p in await product_service.get_account_products(ctx.db, None)]
        if kind in ("card", "all"):
            products += [CardProductResponse.model_validate(p).model_dump()
                         for p in await product_service.get_card_products(ctx.db, None)]
        if keyword:
            matched = [p for p in products if keyword in p["name"] or keyword in p["description"]]
            products = matched or products  # 못 찾으면 전체를 주고 LLM이 고르게 한다
        return to_json(products)

    async def find_recipient_tool(nickname: str) -> str:
        found = await find_recipient(ctx, nickname)
        if found is None:
            return to_json({"error": f'"{nickname}"(으)로 등록된 사람이 없어요.'})
        return to_json({"nickname": found["nickname"], "holder_name": found["holder_name"],
                        "account_num": mask(found["account_num"])})

    return [
        StructuredTool.from_function(coroutine=get_my_accounts, name="get_my_accounts", args_schema=NoArgs,
                                     description="내 계좌 목록(입출금·예금·적금)과 잔액을 조회한다."),
        StructuredTool.from_function(coroutine=get_account_histories, name="get_account_histories",
                                     args_schema=HistoriesArgs, description="계좌 하나의 최근 거래내역을 조회한다."),
        StructuredTool.from_function(coroutine=get_my_cards, name="get_my_cards", args_schema=NoArgs,
                                     description="내 신용·체크카드 목록과 이번 달 사용 누적액을 조회한다."),
        StructuredTool.from_function(coroutine=search_products, name="search_products",
                                     args_schema=ProductSearchArgs, description="은행의 예금·적금·카드 상품을 찾는다."),
        StructuredTool.from_function(coroutine=find_recipient_tool, name="find_recipient", args_schema=RecipientArgs,
                                     description="등록된 수취인을 별칭으로 찾는다."),
    ]


# ---------- 이체 노드용 ----------


async def find_recipient(ctx: ToolContext, nickname: str) -> dict | None:
    """별칭 → {"nickname", "holder_name", "account_num"}. 없으면 None."""
    RecipientArgs(nickname=nickname)
    try:
        recipient = await recipient_service.find_by_nickname(ctx.db, ctx.user, nickname)
    except ApiException:
        return None
    return {"nickname": recipient.nickname, "holder_name": recipient.holder_name, "account_num": recipient.account_num}


async def find_holder(ctx: ToolContext, account_num: str) -> str | None:
    try:
        return await account_service.find_checking_holder(ctx.db, account_num)
    except ApiException:
        return None


async def my_checking_accounts(ctx: ToolContext) -> list[AccountSummaryResponse]:
    accounts = await account_service.get_my_accounts(ctx.db, ctx.user)
    return [a for a in accounts if a.account_type == "checking"]


class PrepareTransferArgs(BaseModel):
    from_checking_account_id: int
    to_account_num: str = Field(min_length=1, max_length=20)
    holder_name: str = Field(min_length=1, max_length=50)
    recipient_nickname: str | None = Field(default=None, max_length=50)
    amount: int = Field(gt=0)


async def prepare_transfer(ctx: ToolContext, args: PrepareTransferArgs) -> tuple[dict, str]:
    """확인 카드(JSON)와 승인 토큰의 jti. 이체는 실행하지 않는다."""
    account = await account_service.get_account(ctx.db, "checking", args.from_checking_account_id, ctx.user)
    # 목소리를 등록한 사용자는 "확인 + 무작위 숫자"로 승인한다 (서버가 화자 인증을 못 하면 버튼 + PIN)
    voice_enrolled = await voice_service.is_enrolled(ctx.db, ctx.user.user_id)
    challenge = digits.new_challenge() if voice_enrolled and voice_available() else None
    token, jti, expires_at = create_confirmation_token(
        user_id=ctx.user.user_id,
        session_id=ctx.session_id,
        from_checking_account_id=account.account_id,
        to_account_num=args.to_account_num,
        amount=args.amount,
        voice_challenge=challenge,
    )
    who = args.recipient_nickname or args.holder_name
    spoken = format_korean_amount(args.amount)
    card = {
        "type": "transfer_confirmation",
        "from_checking_account_id": account.account_id,
        "from_account_num": account.account_num,
        "from_nickname": account.nickname,
        "from_balance": account.balance,
        "to_account_num": args.to_account_num,
        "holder_name": args.holder_name,
        "recipient_nickname": args.recipient_nickname,
        "amount": args.amount,
        "amount_text": spoken,
        "insufficient_balance": account.balance < args.amount,
        "confirmation_token": token,
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
    return card, jti
