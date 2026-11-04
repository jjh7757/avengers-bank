from fastapi import APIRouter

from avengers_bank.core.responses import error_responses

router = APIRouter(prefix="/accounts", tags=["accounts"], responses=error_responses(422))

# TODO: GET   /accounts                                   내 계좌 전체 (3종 합쳐서)
# TODO: POST  /accounts/checking                          입출금 계좌 개설
# TODO: POST  /accounts/deposit                           예금 계좌 개설
# TODO: POST  /accounts/savings                           적금 계좌 개설
# TODO: GET   /accounts/{type}/{account_id}               계좌 상세 (type = checking·deposit·savings)
# TODO: GET   /accounts/{type}/{account_id}/histories     거래내역
# TODO: PATCH /accounts/{type}/{account_id}               별칭, 이체 한도 변경
