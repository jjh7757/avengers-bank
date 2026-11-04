from fastapi import APIRouter

from avengers_bank.core.responses import error_responses

router = APIRouter(prefix="/transfers", tags=["transfers"], responses=error_responses(422))

# TODO: POST /transfers            입출금 → 입출금 이체 (1회·1일 한도 검사)
# TODO: POST /transfers/savings    적금 납입
# TODO: POST /transfers/deposit    예금 입금
