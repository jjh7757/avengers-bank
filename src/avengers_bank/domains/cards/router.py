from fastapi import APIRouter

from avengers_bank.core.responses import error_responses

router = APIRouter(prefix="/cards", tags=["cards"], responses=error_responses(422))

# TODO: GET  /cards                                 내 카드 전체
# TODO: POST /cards/credit                          신용카드 발급
# TODO: POST /cards/debit                           체크카드 발급
# TODO: GET  /cards/{type}/{card_id}                카드 상세 (type = credit·debit)
# TODO: GET  /cards/{type}/{card_id}/histories      사용내역
# TODO: POST /cards/{type}/{card_id}/payments       결제(사용) 등록
