from pydantic import BaseModel, ConfigDict

# TODO: 발급 요청 스키마 — CreditCardCreate, DebitCardCreate (checking_account_id 필수)
# TODO: 상세 응답 스키마 — 카드 종류별 Response, 사용내역 Response
# TODO: CardPaymentCreate — place_of_use, used_amount


class CardSummaryResponse(BaseModel):
    """GET /cards — 신용·체크카드를 한 목록으로 보여줄 때 쓰는 공통 모양"""

    card_type: str  # credit / debit
    card_id: int
    card_num: str
    checking_account_id: int
    accumulated_amount: int

    model_config = ConfigDict(from_attributes=True)
