"""카드 MCP 서버: 내 카드·사용내역 조회, 카드 발급 (결제는 가맹점 쪽 기능이라 도구로 두지 않는다)"""

from typing import Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from avengers_bank.domains.cards.schemas import CreditCardCreate, DebitCardCreate
from avengers_bank.domains.cards.service import card_service
from avengers_bank.mcp_servers.common import bank_tool, mask, new_server

CardType = Literal["credit", "debit"]
READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

server = new_server(
    "avengers-cards",
    "AvengersBank 카드: 내 신용·체크카드와 사용내역 조회, 카드 발급. 카드번호는 뒤 4자리만. 발급은 사용자가 동의한 뒤에만.",
)


def card_json(card) -> dict:
    data = card.model_dump(mode="json")
    data["card_num"] = mask(card.card_num)
    return data


@bank_tool(server, annotations=READ)
async def get_my_cards(db, user) -> dict:
    """내 카드 목록과 이번 달 사용 누적액"""
    return {"cards": [card_json(c) for c in await card_service.get_my_cards(db, user)]}


@bank_tool(server, annotations=READ)
async def get_card_histories(db, user, card_type: CardType, card_id: int, limit: int = Field(default=10, ge=1, le=50)) -> dict:
    """카드 사용내역 (최근 순)"""
    histories = await card_service.get_histories(db, card_type, card_id, user)
    return {"histories": [h.model_dump(mode="json") for h in histories[:limit]]}


@bank_tool(server, annotations=WRITE)
async def issue_debit_card(db, user, product_id: int, checking_account_id: int) -> dict:
    """체크카드 발급 (연결 계좌 = 본인 입출금 계좌). 사용자가 동의한 뒤에만 호출한다"""
    return card_json(await card_service.issue_debit(
        db, DebitCardCreate(product_id=product_id, checking_account_id=checking_account_id), user
    ))


@bank_tool(server, annotations=WRITE)
async def issue_credit_card(db, user, product_id: int, checking_account_id: int, payment_date: int = Field(ge=1, le=31)) -> dict:
    """신용카드 발급 (결제 계좌 = 본인 입출금 계좌, 매월 결제일). 사용자가 동의한 뒤에만 호출한다"""
    data = CreditCardCreate(product_id=product_id, checking_account_id=checking_account_id, payment_date=payment_date)
    return card_json(await card_service.issue_credit(db, data, user))
