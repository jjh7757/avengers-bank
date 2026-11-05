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
    "AvengersBank 카드: 내 신용·체크카드와 사용내역 조회, 카드 발급. 카드번호는 뒤 4자리만. "
    "발급은 prepare_signup(products 서버)으로 받은 이용약관을 사용자에게 보여 주고 동의받은 버전(terms_version)이 있어야 한다.",
)


ISSUED_NOTE = "발급 즉시 앱의 '카드' 메뉴에서 볼 수 있다. 이 서비스에는 실물 카드 배송·수령 절차가 없다."


def card_json(card) -> dict:
    data = card.model_dump(mode="json")
    data["card_num"] = mask(card.card_num)
    return data


def issued_json(card) -> dict:
    """발급 결과 + 사용자에게 안내할 내용 (LLM이 배송 같은 없는 절차를 지어내지 않게)"""
    return {**card_json(card), "next_step": ISSUED_NOTE}


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
async def issue_debit_card(db, user, product_id: int, checking_account_id: int, terms_version: str = Field(min_length=1, max_length=40, description="사용자가 동의한 이용약관 버전 (prepare_signup의 terms.version)")) -> dict:
    """체크카드 발급 (연결 계좌 = 본인 입출금 계좌). 이용약관을 사용자에게 보여 주고 동의받은 뒤에만 호출한다"""
    data = DebitCardCreate(product_id=product_id, checking_account_id=checking_account_id, terms_version=terms_version)
    return issued_json(await card_service.issue_debit(db, data, user))


@bank_tool(server, annotations=WRITE)
async def issue_credit_card(
    db, user, product_id: int, checking_account_id: int, terms_version: str = Field(min_length=1, max_length=40, description="사용자가 동의한 이용약관 버전 (prepare_signup의 terms.version)"), payment_date: int = Field(ge=1, le=31),
) -> dict:
    """신용카드 발급 (결제 계좌 = 본인 입출금 계좌, 매월 결제일). 이용약관을 사용자에게 보여 주고 동의받은 뒤에만 호출한다"""
    data = CreditCardCreate(product_id=product_id, checking_account_id=checking_account_id, terms_version=terms_version, payment_date=payment_date)
    return issued_json(await card_service.issue_credit(db, data, user))
