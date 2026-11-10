"""이체 요청 멱등성 (Idempotency-Key 헤더).

버튼을 두 번 누르거나 네트워크가 끊겨 앱이 다시 보내도 돈은 한 번만 움직인다.
1. begin: 키를 먼저 잡는다(처리 중). 이미 성공한 키면 저장된 결과를 돌려주고, 처리 중이면 409.
2. 이체가 성공하면 complete로 결과를 저장한다.
3. 이체가 실패하면(PIN 필요, 잔액 부족 등) release로 키를 풀어 같은 키로 다시 시도할 수 있게 한다.

이체 커밋과 결과 저장은 별도 트랜잭션이다. 그 사이에 서버가 죽으면 키는 "처리 중"으로 남고,
같은 키 재시도는 409를 받는다. 자동으로 다시 보내지 않으므로 두 번 출금되지는 않는다 (거래내역으로 확인).

타행 이체는 출금을 커밋한 뒤 허브를 부르므로, 그 사이의 실패(연결 끊김으로 요청이 취소됨, DB 오류)에
release가 키를 풀면 같은 키 재시도가 새 이체가 되어 두 번 출금된다. 그래서 출금 트랜잭션 안에서
attach_transfer로 transfer_id를 키에 적고, release는 transfer_id가 있는 키를 지우지 않는다.
그 키로 다시 오면 begin이 transfer_id를 돌려주고, 라우터가 그 타행 이체의 지금 상태로 답한다.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.exceptions import ApiException, BadRequestException, ConflictException
from avengers_bank.domains.transfers.models import IdempotencyRecord
from avengers_bank.domains.transfers.schemas import TransferCreate

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
KEY_TTL = timedelta(hours=24)
# 요청 내용 비교에 쓰는 필드. PIN·승인 토큰·기기 정보는 재시도 때 달라질 수 있고 비밀이라 넣지 않는다
HASHED_FIELDS = ("from_checking_account_id", "to_bank", "to_account_num", "to_account_ref", "amount", "session_id")


@dataclass(frozen=True)
class Replay:
    """같은 키로 다시 온 요청에 돌려줄 것. response(저장된 응답)나 transfer_id(출금이 커밋된 타행 이체) 중 하나다."""

    response: dict[str, Any] | None = None
    transfer_id: str | None = None


def validate_key(key: str) -> str:
    if not KEY_PATTERN.match(key):
        raise BadRequestException(
            code="INVALID_IDEMPOTENCY_KEY", message="Idempotency-Key는 영문·숫자·-·_ 8~64자여야 합니다."
        )
    return key


def request_hash(data: TransferCreate) -> str:
    body = {field: getattr(data, field) for field in HASHED_FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def begin(user_id: int, key: str, body_hash: str) -> Replay | None:
    """키를 잡는다. 이미 처리한 같은 요청이면 Replay(저장된 응답, 또는 출금이 커밋된 타행 이체 ID)를 돌려준다."""
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
            if record.response is not None:
                return Replay(response=record.response)
            if record.transfer_id is not None:
                return Replay(transfer_id=record.transfer_id)
            raise ConflictException(
                code="IDEMPOTENCY_IN_PROGRESS",
                message="같은 이체를 처리하고 있어요. 잠시 후 거래내역을 확인해 주세요.",
            )
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


async def attach_transfer(db: AsyncSession, user_id: int, key: str, transfer_id: str) -> None:
    """타행 출금과 같은 트랜잭션에서 부른다. 출금이 커밋되면 이 키는 그 이체에 묶여 release로 풀리지 않는다."""
    await db.execute(
        update(IdempotencyRecord)
        .where(IdempotencyRecord.user_id == user_id, IdempotencyRecord.key == key)
        .values(transfer_id=transfer_id)
    )


async def release(user_id: int, key: str) -> None:
    """실패한 요청의 키를 풀어 같은 키로 다시 시도할 수 있게 한다. 돈이 이미 나간 키(transfer_id)는 남긴다."""
    async with SessionLocal() as db, db.begin():
        await db.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.key == key,
                IdempotencyRecord.transfer_id.is_(None),
            )
        )
