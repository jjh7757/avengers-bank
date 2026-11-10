from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from avengers_bank.domains.interbank.reserve_requests import MAX_AMOUNT


class HubReserve(BaseModel):
    """허브가 말하는 우리 예치금 (ClearingHub SPEC 10.2 GET /v1/reserve)."""

    bank_code: str | None = None
    balance: int | None = Field(default=None, description="허브 예치금 잔액. 마이너스일 수 있다")
    net_debit_cap: int | None = Field(default=None, description="순채무한도")
    exposure: int | None = Field(default=None, description="미정산 순채무")
    available: int | None = Field(default=None, description="지금 더 보낼 수 있는 금액 = balance + net_debit_cap − exposure")


class TreasuryResponse(BaseModel):
    vault_cash: int = Field(description="금고 현금 (CASH_VAULT 원장 합)")
    ledger_hub_reserve: int = Field(description="우리 장부의 허브 예치금 (HUB_RESERVE 원장 합)")
    hub_reserve: HubReserve | None = Field(description="허브가 말하는 예치금. 허브가 응답하지 않으면 null")
    hub_reserve_error: str | None = Field(
        description="hub_reserve가 null인 이유: INTERBANK_DISABLED(허브 설정 없음), HUB_TIMEOUT(응답 없음), HUB_ERROR, 허브 오류 코드"
    )
    open_deposit_amount: int = Field(description="결정을 기다리는 입금 신청 합 (SENDING·PENDING)")
    deposit_available: int = Field(description="지금 입금 신청할 수 있는 금액 = 금고 현금 − open_deposit_amount (0 이상)")
    open_request_count: int = Field(description="결정을 기다리는 신청 수 (입금+인출)")
    open_deposit_count: int
    open_withdraw_count: int
    suspense_balance: int = Field(description="타행 송금 중간 계정(INTERBANK_SUSPENSE) 잔액: 고객 계좌에서 빠졌지만 아직 확정 안 된 돈")
    reconcile_problems: list[str] = Field(description="장부 대사 불일치 목록 (비어 있으면 정상)")
    interbank_enabled: bool = Field(description="허브 설정이 있는지. false면 신청·취소·동기화는 503 INTERBANK_DISABLED")
    checked_at: datetime


class ReserveRequestCreate(BaseModel):
    kind: Literal["DEPOSIT", "WITHDRAW"] = Field(description="DEPOSIT: 금고 현금 → 허브 예치금, WITHDRAW: 반대")
    amount: int = Field(ge=1, le=MAX_AMOUNT)
    memo: str = Field(default="", max_length=200)


class ReserveRequestResponse(BaseModel):
    request_id: int
    request_ref: str
    kind: str
    amount: int
    memo: str
    status: str = Field(description="SENDING(허브 접수 확인 전) / PENDING(허브 관리자 결정 대기) / APPROVED / REJECTED / CANCELLED / FAILED(허브가 접수 전 거절)")
    hub_request_id: int | None
    reject_reason: str | None
    hub_balance_after: int | None
    created_at: datetime
    decided_at: datetime | None
    booked_at: datetime | None = Field(description="승인을 우리 장부에 반영한 시각 (금고 현금 ↔ 예치금)")

    model_config = ConfigDict(from_attributes=True)


class AuditLogResponse(BaseModel):
    log_id: int
    admin_user_id: int
    admin_login_id: str
    action: str
    target: str | None
    detail: dict[str, Any]
    result: Literal["OK", "FAILED"]
    error_code: str | None
    client_ip: str | None
    created_at: datetime
