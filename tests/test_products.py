import pytest

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
