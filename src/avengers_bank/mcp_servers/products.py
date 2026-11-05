"""상품 MCP 서버: 예금·적금·카드 상품 검색과 상세, 가입 화면(이용약관) 준비"""

from typing import Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.products.schemas import AccountProductResponse, CardProductResponse
from avengers_bank.domains.products.service import product_service
from avengers_bank.mcp_servers.common import bank_tool, new_server

READ = ToolAnnotations(readOnlyHint=True)

server = new_server(
    "avengers-products",
    "AvengersBank 상품: 입출금·예금·적금 계좌 상품과 신용·체크카드 상품 안내, 가입 화면(이용약관 + 가입 조건) 준비",
)


@bank_tool(server, annotations=READ)
async def search_products(
    db,
    user,
    kind: Literal["account", "card", "all"] = "all",
    keyword: str | None = Field(default=None, max_length=30, description="이름·설명에서 찾을 단어 (예: 적금, 청년)"),
) -> dict:
    """상품 찾기. 키워드로 못 찾으면 전체 목록을 돌려준다"""
    # 약관·FAQ 같은 자세한 규칙은 knowledge 서버의 search_terms가 맡는다
    products = []
    if kind in ("account", "all"):
        products += [AccountProductResponse.model_validate(p).model_dump(mode="json")
                     for p in await product_service.get_account_products(db, None)]
    if kind in ("card", "all"):
        products += [CardProductResponse.model_validate(p).model_dump(mode="json")
                     for p in await product_service.get_card_products(db, None)]
    if keyword:
        matched = [p for p in products if keyword in p["name"] or keyword in p["description"]]
        products = matched or products
    return {"products": products}


@bank_tool(server, annotations=READ)
async def get_product(db, user, kind: Literal["account", "card"], product_id: int) -> dict:
    """상품 상세"""
    if kind == "account":
        return AccountProductResponse.model_validate(await product_service.get_account_product(db, product_id)).model_dump(mode="json")
    return CardProductResponse.model_validate(await product_service.get_card_product(db, product_id)).model_dump(mode="json")


# 상품 종류별로 가입 화면에 미리 채울 수 있는 값
SIGNUP_FIELDS = {
    "CHECKING": (),
    "DEPOSIT": ("term_months",),
    "SAVINGS": ("term_months", "monthly_payment", "monthly_deposit_date"),
    "DEBIT": ("checking_account_id",),
    "CREDIT": ("checking_account_id", "payment_date"),
}
SIGNUP_NEXT_STEP = (
    "가입 화면을 사용자 화면에 띄웠다. 아직 만들어지지 않았다. 사용자가 화면에서 이용약관을 읽고 동의한 뒤 "
    "남은 항목을 채우고 '가입하기'를 눌러야 만들어진다. 약관에서 꼭 알아야 할 점 한두 가지를 짧게 말하고 이렇게 안내한다."
)


@bank_tool(server, annotations=READ)
async def prepare_signup(
    db,
    user,
    kind: Literal["account", "card"],
    product_id: int,
    term_months: int | None = Field(default=None, ge=1, le=60, description="예금·적금 가입 기간(개월)"),
    monthly_payment: int | None = Field(default=None, gt=0, description="적금 월 납입액(원)"),
    monthly_deposit_date: int | None = Field(default=None, ge=1, le=31, description="적금 매월 납입일"),
    checking_account_id: int | None = Field(default=None, description="카드에 연결할 내 입출금 계좌 (체크카드 출금·신용카드 결제)"),
    payment_date: int | None = Field(default=None, ge=1, le=31, description="신용카드 매월 결제일"),
) -> dict:
    """상품 가입 화면 준비: 그 상품의 이용약관과 사용자가 말한 가입 조건을 사용자 화면에 띄운다.
    계좌를 만들거나 카드를 발급하지는 않는다. 사용자가 화면에서 약관에 동의하고 '가입하기'를 눌러야 만들어진다.
    가입·개설·발급을 원하면 조건을 다 묻지 말고 이 도구를 부른다 (빠진 조건은 화면에서 채운다)"""
    terms = await product_service.get_terms(db, kind, product_id)
    given = {"term_months": term_months, "monthly_payment": monthly_payment, "monthly_deposit_date": monthly_deposit_date,
             "checking_account_id": checking_account_id, "payment_date": payment_date}
    prefill = {k: given[k] for k in SIGNUP_FIELDS[terms.product_type] if given[k] is not None}
    if "checking_account_id" in prefill:
        async with db.begin():  # 남의 계좌를 화면에 넣지 않게 (발급 때도 다시 검사한다)
            await account_service.get_owned_account(db, "checking", prefill["checking_account_id"], user.user_id)
    return {
        "product": {"kind": kind, "product_id": product_id, "type": terms.product_type, "name": terms.product_name},
        "terms": {"title": terms.title, "version": terms.version,
                  "sections": [s.model_dump() for s in terms.sections]},
        "prefill": prefill,
        "next_step": SIGNUP_NEXT_STEP,
    }
