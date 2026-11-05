import pytest
from sqlalchemy import select

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.products.models import TermsAgreement
from tests.conftest import DEBIT_PRODUCT, SAVINGS_PRODUCT, open_checking, terms_version

pytestmark = pytest.mark.anyio


async def test_list_account_products(client):
    response = await client.get("/products/accounts")
    assert response.status_code == 200
    assert len(response.json()["data"]) == 5


async def test_list_account_products_filter_by_type(client):
    response = await client.get("/products/accounts", params={"type": "SAVINGS"})
    types = {product["type"] for product in response.json()["data"]}
    assert types == {"SAVINGS"}


async def test_list_account_products_invalid_type(client):
    response = await client.get("/products/accounts", params={"type": "LOAN"})
    assert response.status_code == 422


async def test_get_account_product(client):
    response = await client.get("/products/accounts/1")
    assert response.status_code == 200
    assert response.json()["data"]["type"] == "CHECKING"


async def test_get_account_product_not_found(client):
    response = await client.get("/products/accounts/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


async def test_list_and_get_card_products(client):
    response = await client.get("/products/cards", params={"type": "DEBIT"})
    data = response.json()["data"]
    assert [product["type"] for product in data] == ["DEBIT"]

    response = await client.get(f"/products/cards/{data[0]['product_id']}")
    assert response.status_code == 200


async def test_terms_endpoint(client):
    response = await client.get(f"/products/accounts/{SAVINGS_PRODUCT}/terms")
    assert response.status_code == 200
    terms = response.json()["data"]
    assert terms["product_name"] == "캡틴 꾸준적금" and terms["product_type"] == "SAVINGS"
    assert terms["version"] == terms_version("account", SAVINGS_PRODUCT)
    assert "중도 해지" in [s["title"] for s in terms["sections"]]

    card = (await client.get(f"/products/cards/{DEBIT_PRODUCT}/terms")).json()["data"]
    assert card["product_kind"] == "card" and "연회비" in [s["title"] for s in card["sections"]]
    assert (await client.get("/products/cards/999/terms")).status_code == 404


async def test_opening_requires_current_terms(client, user):
    """약관 버전이 없거나(422) 지금 버전이 아니면(400) 개설·발급하지 않고, 동의하면 기록을 남긴다"""
    body = {"product_id": SAVINGS_PRODUCT, "term_months": 12, "monthly_payment": 100_000, "monthly_deposit_date": 1}
    assert (await client.post("/accounts/savings", headers=user, json=body)).status_code == 422
    response = await client.post("/accounts/savings", headers=user, json={**body, "terms_version": "old-version"})
    assert response.status_code == 400 and response.json()["error"]["code"] == "TERMS_NOT_AGREED"

    response = await client.post("/accounts/savings", headers=user,
                                 json={**body, "terms_version": terms_version("account", SAVINGS_PRODUCT)})
    assert response.status_code == 201
    savings_id = response.json()["data"]["account_id"]

    async with SessionLocal() as db:
        [agreement] = (await db.scalars(select(TermsAgreement))).all()
    assert (agreement.product_kind, agreement.product_id, agreement.target_type, agreement.target_id) == (
        "account", SAVINGS_PRODUCT, "savings", savings_id
    )
    assert agreement.terms_version == terms_version("account", SAVINGS_PRODUCT)

    checking = await open_checking(client, user)
    response = await client.post("/cards/debit", headers=user, json={
        "product_id": DEBIT_PRODUCT, "checking_account_id": checking["account_id"], "terms_version": "old-version"})
    assert response.json()["error"]["code"] == "TERMS_NOT_AGREED"
