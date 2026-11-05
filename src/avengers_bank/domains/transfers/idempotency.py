"""이체 요청 멱등성 (Idempotency-Key 헤더).

버튼을 두 번 누르거나 네트워크가 끊겨 앱이 다시 보내도 돈은 한 번만 움직인다.
1. begin: 키를 먼저 잡는다(처리 중). 이미 성공한 키면 저장된 결과를 돌려주고, 처리 중이면 409.
2. 이체가 성공하면 complete로 결과를 저장한다.
3. 이체가 실패하면(PIN 필요, 잔액 부족 등) release로 키를 풀어 같은 키로 다시 시도할 수 있게 한다.

이체 커밋과 결과 저장은 별도 트랜잭션이다. 그 사이에 서버가 죽으면 키는 "처리 중"으로 남고,
같은 키 재시도는 409를 받는다. 자동으로 다시 보내지 않으므로 두 번 출금되지는 않는다 (거래내역으로 확인).
"""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.exceptions import ApiException, BadRequestException, ConflictException
from avengers_bank.domains.transfers.models import IdempotencyRecord
from avengers_bank.domains.transfers.schemas import TransferCreate

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
KEY_TTL = timedelta(hours=24)
# 요청 내용 비교에 쓰는 필드. PIN·승인 토큰·기기 정보는 재시도 때 달라질 수 있고 비밀이라 넣지 않는다
HASHED_FIELDS = ("from_checking_account_id", "to_bank", "to_account_num", "to_account_ref", "amount", "session_id")


def validate_key(key: str) -> str:
    if not KEY_PATTERN.match(key):
        raise BadRequestException(
            code="INVALID_IDEMPOTENCY_KEY", message="Idempotency-Key는 영문·숫자·-·_ 8~64자여야 합니다."
        )
    return key


def request_hash(data: TransferCreate) -> str:
    body = {field: getattr(data, field) for field in HASHED_FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def begin(user_id: int, key: str, body_hash: str) -> dict[str, Any] | None:
    """키를 잡는다. 이미 성공한 같은 요청이면 저장된 응답(dict)을 돌려준다."""
    async with SessionLocal() as db, db.begin():
        await db.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.created_at < datetime.now(timezone.utc) - KEY_TTL)
        )
        record = await db.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.user_id == user_id, IdempotencyRecord.key == key)
        )
        if record is not None:
            if record.request_hash != body_hash:
                raise ApiException(
                    422, "IDEMPOTENCY_KEY_REUSED", "이미 다른 이체에 쓴 Idempotency-Key입니다. 새 키로 보내 주세요."
                )
            if record.response is None:
                raise ConflictException(
                    code="IDEMPOTENCY_IN_PROGRESS",
                    message="같은 이체를 처리하고 있어요. 잠시 후 거래내역을 확인해 주세요.",
                )
            return record.response
    try:
        async with SessionLocal() as db, db.begin():
            db.add(IdempotencyRecord(user_id=user_id, key=key, request_hash=body_hash))
    except IntegrityError:
        # 거의 동시에 같은 키로 두 요청이 왔다: 먼저 잡은 쪽이 처리한다
        raise ConflictException(
            code="IDEMPOTENCY_IN_PROGRESS", message="같은 이체를 처리하고 있어요. 잠시 후 거래내역을 확인해 주세요."
        ) from None
    return None


async def complete(user_id: int, key: str, response: dict[str, Any]) -> None:
    async with SessionLocal() as db, db.begin():
        record = await db.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.user_id == user_id, IdempotencyRecord.key == key)
        )
        if record is not None:
            record.response = response


async def release(user_id: int, key: str) -> None:
    async with SessionLocal() as db, db.begin():
        await db.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.user_id == user_id, IdempotencyRecord.key == key)
        )
