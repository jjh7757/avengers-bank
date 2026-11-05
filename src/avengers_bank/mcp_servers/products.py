"""상품 MCP 서버: 예금·적금·카드 상품 검색과 상세"""

from typing import Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from avengers_bank.domains.products.schemas import AccountProductResponse, CardProductResponse
from avengers_bank.domains.products.service import product_service
from avengers_bank.mcp_servers.common import bank_tool, new_server

READ = ToolAnnotations(readOnlyHint=True)

server = new_server("avengers-products", "AvengersBank 상품: 입출금·예금·적금 계좌 상품과 신용·체크카드 상품 안내")


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
