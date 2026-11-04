from fastapi import APIRouter

from avengers_bank.core.responses import error_responses

router = APIRouter(prefix="/products", tags=["products"], responses=error_responses(422))

# TODO: GET /products/accounts?type=            계좌 상품 목록
# TODO: GET /products/accounts/{product_id}     계좌 상품 상세
# TODO: GET /products/cards?type=               카드 상품 목록
# TODO: GET /products/cards/{product_id}        카드 상품 상세
