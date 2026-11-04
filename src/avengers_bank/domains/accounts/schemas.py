from datetime import datetime

from pydantic import BaseModel, ConfigDict

# TODO: 개설 요청 스키마 — CheckingAccountCreate, DepositAccountCreate, SavingsAccountCreate
# TODO: 상세 응답 스키마 — 계좌 종류별 Response, 거래내역 Response
# TODO: 수정 요청 스키마 — 별칭, 이체 한도


class AccountSummaryResponse(BaseModel):
    """GET /accounts — 3종 계좌를 한 목록으로 보여줄 때 쓰는 공통 모양"""

    account_type: str  # checking / deposit / savings
    account_id: int
    account_num: str
    balance: int
    nickname: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
