from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class InterbankStatus(StrEnum):
    PENDING = "PENDING"  # 출금해 타행 송금 중간 계정에 두고 허브 결과를 기다림
    COMPLETED = "COMPLETED"  # 받는 은행 입금 확인 → 중간 계정에서 그 은행 정산 계정으로
    FAILED = "FAILED"  # 받는 은행·허브가 거절 → 중간 계정에서 고객 계좌로 되돌림


class LedgerAccount(StrEnum):
    """은행 내부 계정 (고객 계좌가 아님)."""

    SUSPENSE = "INTERBANK_SUSPENSE"  # 타행 송금 중간 계정: 고객 계좌에서 빠졌지만 아직 확정되지 않은 돈
    SETTLEMENT = "INTERBANK_SETTLEMENT"  # 타행 정산 계정 (은행별): + 우리가 그 은행에 줄 돈, - 받을 돈
    # 허브에 맡긴 모의 예치금 (SPEC 10.2). 은행별이 아니라 하나이고 bank_code는 허브 "000"이다.
    # 위 두 계정은 고객 예금처럼 "우리가 갚을 돈"이고, 이것만 "우리가 가진 돈"이라 정산 때 둘이 같은 방향으로 준다
    HUB_RESERVE = "HUB_RESERVE"


class LedgerEvent(StrEnum):
    DEBIT = "DEBIT"  # 보내기 출금: 고객 → 중간 계정
    COMPLETE = "COMPLETE"  # 보내기 완료: 중간 계정 → 정산 계정
    REFUND = "REFUND"  # 보내기 실패: 중간 계정 → 고객
    RECEIVE = "RECEIVE"  # 받기: 정산 계정 → 고객
    SETTLE = "SETTLE"  # 허브 정산 확정 (SPEC 10.6의 4): 정산 계정 → 예치금 계정. transfer_id는 "settle:{run_id}:{은행}"


class EvidenceDirection(StrEnum):
    """hub_evidence 한 행이 무엇인지 (SPEC 2.5 보관, SETTLEMENT_PLAN 12.3)."""

    TRANSFER_OUT = "TRANSFER_OUT"  # 우리 → 허브 POST /v1/transfers 요청 (처음·확인 중 재전송)
    TRANSFER_REPLY = "TRANSFER_REPLY"  # 그 요청에 대한 허브 응답
    RECEIVE_IN = "RECEIVE_IN"  # 허브 → 우리 /interbank/receive·/interbank/receive/{id} 요청 (서명 검증을 통과한 것만)
    RECEIVE_REPLY = "RECEIVE_REPLY"  # 그 요청에 대한 우리 응답 (응답 서명을 붙였으면 그 헤더까지)


class ReconResult(StrEnum):
    """허브 정산 run 하나를 우리 장부와 맞춘 결과 (SPEC 10.6의 3)."""

    MATCHED = "MATCHED"  # transfer_id·방향·금액·상대 은행과 포지션 순액이 모두 같다
    CHECKING = "CHECKING"  # 허브는 COMPLETED인데 우리는 아직 PENDING인 거래가 있다 (결과를 확인한 뒤 다시 본다)
    MISMATCH = "MISMATCH"  # 허브에만 있거나 내용이 다른 거래가 있다. 자동 처리를 멈추고 허브 관리자와 맞춘다


class InterbankLedgerEntry(Base):
    """내부 계정 분개. 잔액은 컬럼으로 두지 않고 amount의 합으로 계산한다 (한 행을 모든 이체가 잠그지 않게).

    고객 쪽 변화는 checking_account_histories에 있다. 한 사건마다 '고객 쪽 변화 + 이 표의 변화 = 0'이다.
    (transfer_id, event, account)가 유일해서 같은 사건을 두 번 기록할 수 없다."""

    __tablename__ = "interbank_ledger"
    __table_args__ = (UniqueConstraint("transfer_id", "event", "account", name="uq_interbank_ledger_event"),)

    entry_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transfer_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    account: Mapped[str] = mapped_column(String(30), nullable=False)
    bank_code: Mapped[str] = mapped_column(String(3), nullable=False)  # 상대 은행
    event: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 그 내부 계정 잔액의 증감
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 이 분개가 맞춰진 허브 정산 run (SPEC 10.6의 4). COMPLETE·RECEIVE의 정산 계정 줄은 그 run이 확정돼 장부를
    # 정리할 때 찍고, SETTLE 줄은 처음부터 찍는다. NULL인 COMPLETE·RECEIVE 줄이 다음 대사의 후보다
    hub_run_id: Mapped[int | None] = mapped_column(Integer, index=True)


class SettlementReconciliation(Base):
    """허브 정산 run 하나의 대사 결과 (SPEC 10.6). 같은 run을 다시 보면 이 행을 갱신한다.
    settled_at이 있으면 그 run의 SETTLE 분개를 남긴 것이다 (run마다 한 번)."""

    __tablename__ = "settlement_reconciliations"

    hub_run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    settle_date: Mapped[date] = mapped_column(Date, nullable=False)
    hub_status: Mapped[str] = mapped_column(String(20), nullable=False)  # 마지막으로 본 허브 상태 DRAFT / SETTLED
    hub_net_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 허브 position.net_amount (받을 돈 − 줄 돈)
    our_net_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 일치한 거래로 계산한 같은 값
    result: Mapped[str] = mapped_column(String(20), nullable=False)  # ReconResult
    # 차이 목록 JSON: hub_only, differs, checking, ours_only, ours_only_stale, net (빈 항목은 넣지 않는다)
    diff_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterbankTransfer(Base):
    """우리 고객이 다른 은행으로 보낸 이체. 상태가 PENDING인 금액의 합은 중간 계정 잔액과 같아야 한다."""

    __tablename__ = "interbank_transfers"

    transfer_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # 허브에 보내는 UUID (멱등성 키)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), index=True, nullable=False)
    checking_account_id: Mapped[int] = mapped_column(
        ForeignKey("checking_accounts.checking_account_id"), nullable=False
    )
    to_bank: Mapped[str] = mapped_column(String(3), nullable=False)
    to_account: Mapped[str] = mapped_column(String(50), nullable=False)  # 내 다른 은행 계좌로 보낼 때는 가린 번호
    # 본인 계좌 조회로 받은 허브 참조값 (SPEC 9.3). 있으면 허브에 to_account 대신 이것을 보낸다
    to_account_ref: Mapped[str | None] = mapped_column(String(64))
    to_holder_name: Mapped[str | None] = mapped_column(String(50))
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memo: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    fail_code: Mapped[str | None] = mapped_column(String(40))
    fail_message: Mapped[str | None] = mapped_column(String(200))
    check_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 허브에 결과를 물어본 횟수
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterbankReceipt(Base):
    """다른 은행에서 우리 고객에게 들어온 입금. transfer_id로 한 번만 입금한다 (SPEC 4.2)."""

    __tablename__ = "interbank_receipts"

    transfer_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    checking_account_id: Mapped[int] = mapped_column(
        ForeignKey("checking_accounts.checking_account_id"), index=True, nullable=False
    )
    from_bank: Mapped[str] = mapped_column(String(3), nullable=False)
    from_bank_name: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    from_account: Mapped[str] = mapped_column(String(50), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memo: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HubAccountQuery(Base):
    """허브가 우리에게 물어본 본인 명의 계좌 조회 기록 (SPEC 9.4 규칙 5: 시각, ci, 돌려준 계좌 수).
    허브의 조회 기록(lookup_id·consent_id)과 맞춰 보거나, 누가 어떤 사람을 자주 조회하는지 볼 때 쓴다.
    ci는 고객 테이블에도 있는 값이라 그대로 두고, 고객이 없었던 조회도 남긴다 (account_count = 0)."""

    __tablename__ = "hub_account_queries"

    query_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ci: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    account_count: Mapped[int] = mapped_column(Integer, nullable=False)
    queried_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OwnAccountLookup(Base):
    """다른 은행 내 계좌 불러오기 동의 기록 (SPEC 9.2). consent_id를 허브에 보내고, 허브 조회 기록과 맞춰 볼 수 있다."""

    __tablename__ = "own_account_lookups"

    consent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), index=True, nullable=False)
    hub_lookup_id: Mapped[str | None] = mapped_column(String(36))
    account_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OwnAccountRef(Base):
    """허브가 준 account_ref를 받은 사용자에게 묶어 둔다. 같은 은행의 다른 고객이 쓰지 못하게 한다."""

    __tablename__ = "own_account_refs"

    ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), index=True, nullable=False)
    consent_id: Mapped[str] = mapped_column(ForeignKey("own_account_lookups.consent_id"), nullable=False)
    bank_code: Mapped[str] = mapped_column(String(3), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(50), nullable=False)
    account_masked: Mapped[str] = mapped_column(String(50), nullable=False)
    product_name: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HubEvidence(Base):
    """허브와 주고받은 이체 관련 요청·응답의 원문 (SPEC 2.5 "보관", 분쟁 때 꺼내 보일 것). 추가만 하고 고치거나 지우지 않는다.

    body는 서명한 바이트 그대로다 (JSON으로 풀었다 다시 만들면 서명이 맞지 않는다).
    다시 검증할 때: 요청은 method·path·X-Timestamp·X-Signature로 (2.2), 응답은 http_status·X-Response-*와
    바로 앞 요청 행의 X-Signature로 (2.5). 결과 조회·대사 조회·수취 조회는 남기지 않는다 (이체 관련만)."""

    __tablename__ = "hub_evidence"

    evidence_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transfer_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)  # EvidenceDirection
    method: Mapped[str | None] = mapped_column(String(10))  # 요청만: 서명에 쓴 METHOD
    path: Mapped[str | None] = mapped_column(String(200))  # 요청만: 서명에 쓴 규격 PATH (/v1/transfers, /receive/{id})
    http_status: Mapped[int | None] = mapped_column(Integer)  # 응답만: 응답 서명 메시지의 STATUS
    # 서명 관련 헤더만 (X-Bank-Code, X-Timestamp, X-Signature, X-Signature-Alg, X-Request-ID, X-Response-*). X-Api-Key는 넣지 않는다
    headers_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    body: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    signature_alg: Mapped[str | None] = mapped_column(String(10))  # hmac | ed25519 | NULL (서명 없는 응답)
    # 받은 쪽의 검증 결과: TRANSFER_REPLY는 허브 응답 서명(검증 안 하는 hmac 모드·서명 없음은 NULL),
    # RECEIVE_IN은 True(통과한 것만 남긴다). 우리가 만든 TRANSFER_OUT·RECEIVE_REPLY는 NULL
    signature_valid: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
