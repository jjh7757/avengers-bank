"""발표 시연용 데이터 만들기·초기화 (docs/DEMO.md).

    uv run python scripts/demo_seed.py

배포 서버에서는 컨테이너 안에서: docker exec avengers-bank python scripts/demo_seed.py (docs/DEPLOY.md)

여러 번 실행해도 같은 상태로 돌아간다. 시연 사용자(demo)의 계좌·거래·대화·FDS 기록·카드·수취인을 지우고 다시 만든다.
등록한 목소리(voice_profiles)는 남긴다 (설정 화면에서 한 번만 등록하면 된다).

만드는 것
- demo(홍길동): 입출금 "생활비" 320만원, "월급" 150만원, 체크카드, 이체 PIN, 가입 3년 전
- 수취인: 엄마(김영희), 집주인(박집주인)
- 지난 30일 평소 이체 30건 (낮 시간, 엄마·집주인에게 2만~65만원) + 급여 입금 → FDS가 "평소 패턴"을 안다
- 처음 보는 계좌 2개: 시나리오 2(중고차 판매자), 시나리오 3(사기 "안전계좌")
"""

import asyncio
import os
import random
import selectors
import sys
from datetime import timedelta

from sqlalchemy import delete, select, update

from avengers_bank.core.clock import KST, real_now_utc
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.security import hash_password
from avengers_bank.domains.accounts.models import (
    CheckingAccount,
    CheckingAccountHistory,
    DepositAccount,
    DepositAccountHistory,
    HistoryType,
    SavingsAccount,
    SavingsAccountHistory,
)
from avengers_bank.domains.accounts.schemas import CheckingAccountCreate
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.cards.models import CreditCard, CreditCardHistory, DebitCard, DebitCardHistory
from avengers_bank.domains.chat.models import ChatMessage, ChatSession
from avengers_bank.domains.fds.models import FdsLog, UserDevice
from avengers_bank.domains.products.seed import seed_products
from avengers_bank.domains.recipients.models import Recipient
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.schemas import UserResponse

# 로컬 기본값은 저장소에 공개돼 있다. 누구나 접속하는 배포 서버에서는 서버 .env에만 둔 값을 쓴다 (docs/DEPLOY.md)
PASSWORD = os.environ.get("DEMO_SEED_PASSWORD") or "demo1234!"
PIN = os.environ.get("DEMO_SEED_PIN") or "246810"
FROM_ENV = bool(os.environ.get("DEMO_SEED_PASSWORD"))
USERS = {  # login_id: 이름
    "demo": "홍길동",
    "demo_mom": "김영희",
    "demo_landlord": "박집주인",
    "demo_seller": "최판매",
    "demo_scammer": "금융보호센터",
}
rng = random.Random(2026)


async def upsert_users(db) -> dict[str, User]:
    users = {}
    hashed = hash_password(PASSWORD)
    for login_id, name in USERS.items():
        user = await db.scalar(select(User).where(User.login_id == login_id))
        if user is None:
            user = User(login_id=login_id, hashed_password=hashed, name=name, phone="010-0000-0000")
            db.add(user)
        user.hashed_password, user.name = hashed, name
        users[login_id] = user
    await db.flush()
    demo = users["demo"]
    demo.hashed_pin = hash_password(PIN)
    demo.created_at = real_now_utc() - timedelta(days=365 * 3)
    return users


async def wipe(db, user_ids: list[int]) -> None:
    """시연 사용자들의 데이터를 지운다 (사용자 행과 목소리 등록은 남김)"""
    sessions = select(ChatSession.session_id).where(ChatSession.user_id.in_(user_ids))
    checking = select(CheckingAccount.checking_account_id).where(CheckingAccount.user_id.in_(user_ids))
    for statement in [
        delete(ChatMessage).where(ChatMessage.session_id.in_(sessions)),
        delete(ChatSession).where(ChatSession.user_id.in_(user_ids)),
        delete(FdsLog).where(FdsLog.user_id.in_(user_ids)),
        delete(UserDevice).where(UserDevice.user_id.in_(user_ids)),
        delete(Recipient).where(Recipient.user_id.in_(user_ids)),
        delete(DebitCardHistory).where(DebitCardHistory.debit_card_id.in_(select(DebitCard.debit_card_id).where(DebitCard.user_id.in_(user_ids)))),
        delete(CreditCardHistory).where(CreditCardHistory.credit_card_id.in_(select(CreditCard.credit_card_id).where(CreditCard.user_id.in_(user_ids)))),
        delete(DebitCard).where(DebitCard.user_id.in_(user_ids)),
        delete(CreditCard).where(CreditCard.user_id.in_(user_ids)),
        delete(CheckingAccountHistory).where(CheckingAccountHistory.checking_account_id.in_(checking)),
        delete(DepositAccountHistory).where(DepositAccountHistory.deposit_account_id.in_(select(DepositAccount.deposit_account_id).where(DepositAccount.user_id.in_(user_ids)))),
        delete(SavingsAccountHistory).where(SavingsAccountHistory.savings_account_id.in_(select(SavingsAccount.savings_account_id).where(SavingsAccount.user_id.in_(user_ids)))),
        delete(CheckingAccount).where(CheckingAccount.user_id.in_(user_ids)),
        delete(DepositAccount).where(DepositAccount.user_id.in_(user_ids)),
        delete(SavingsAccount).where(SavingsAccount.user_id.in_(user_ids)),
    ]:
        await db.execute(statement)


async def open_account(db, user: User, nickname: str | None, balance: int, account_num: str) -> CheckingAccount:
    """발표자가 말하기 쉽도록 계좌번호를 고정한다 (시연용 번호대 110-9xx)."""
    detail = await account_service.open_checking(
        db, CheckingAccountCreate(product_id=1, nickname=nickname), UserResponse.model_validate(user)
    )
    async with db.begin():
        await db.execute(update(CheckingAccount).where(CheckingAccount.checking_account_id == detail.account_id)
                         .values(balance=balance, account_num=account_num))
        return await db.get(CheckingAccount, detail.account_id)


def daytime(days_ago: int) -> object:
    local = (real_now_utc() - timedelta(days=days_ago)).astimezone(KST)
    return local.replace(hour=rng.randint(10, 19), minute=rng.randint(0, 59), second=0, microsecond=0)


async def main() -> None:
    async with SessionLocal() as db:
        async with db.begin():
            await seed_products(db)
            users = await upsert_users(db)
            await wipe(db, [u.user_id for u in users.values()])
            for user in users.values():
                await db.refresh(user)

        living = await open_account(db, users["demo"], "생활비", 3_200_000, "110-900-000001")
        salary = await open_account(db, users["demo"], "월급", 1_500_000, "110-900-000002")
        mom = await open_account(db, users["demo_mom"], None, 500_000, "110-900-100001")
        landlord = await open_account(db, users["demo_landlord"], None, 0, "110-900-100002")
        seller = await open_account(db, users["demo_seller"], None, 0, "110-900-222222")
        scammer = await open_account(db, users["demo_scammer"], None, 0, "110-900-333333")

        async with db.begin():
            demo = users["demo"]
            db.add_all([
                Recipient(user_id=demo.user_id, account_num=mom.account_num, holder_name="김영희", nickname="엄마"),
                Recipient(user_id=demo.user_id, account_num=landlord.account_num, holder_name="박집주인", nickname="집주인"),
            ])
            # 지난 30일 평소 이체 30건: 대부분 엄마에게 소액, 월세 1번. 오늘 것은 없다 (1일 한도에 안 걸리게)
            plan = [(landlord, 650_000, 25)] + [(mom, rng.choice([20_000, 30_000, 50_000, 100_000, 150_000, 200_000]), d)
                                                for d in sorted(rng.sample(range(1, 30), 29), reverse=True)]
            for target, amount, days_ago in plan:
                at = daytime(days_ago)
                common = {"date": at, "from_account": living.account_num, "sending_account": target.account_num}
                db.add(CheckingAccountHistory(checking_account_id=living.checking_account_id, change_amount=-amount,
                                              type=HistoryType.TRANSFER_OUT, **common))
                db.add(CheckingAccountHistory(checking_account_id=target.checking_account_id, change_amount=amount,
                                              type=HistoryType.TRANSFER_IN, **common))
            db.add(CheckingAccountHistory(checking_account_id=salary.checking_account_id, change_amount=3_500_000,
                                          type=HistoryType.DEPOSIT, date=daytime(10), from_account="회사 급여"))
            for recipient_account in (mom, landlord):
                last = max(daytime(d) for t, _, d in plan if t is recipient_account)
                await db.execute(update(Recipient).where(Recipient.user_id == demo.user_id,
                                                         Recipient.account_num == recipient_account.account_num).values(last_sent_at=last))
            card = DebitCard(user_id=demo.user_id, product_id=2, checking_account_id=living.checking_account_id,
                             card_num=f"9420-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
                             accumulated_amount=0)
            db.add(card)
            await db.flush()
            for place, amount, days_ago in [("동네 편의점", 4_500, 3), ("단골 카페", 5_800, 2), ("약국", 12_000, 1)]:
                db.add(DebitCardHistory(debit_card_id=card.debit_card_id, place_of_use=place, used_amount=amount, time=daytime(days_ago)))
                card.accumulated_amount += amount

    print("시연 데이터를 만들었습니다.\n")
    if FROM_ENV:  # 서버 값은 출력하지 않는다 (SSM·로그에 남지 않게)
        print("  로그인      demo / 비밀번호·이체 PIN은 서버 .env의 DEMO_SEED_PASSWORD·DEMO_SEED_PIN")
    else:
        print(f"  로그인      demo / {PASSWORD}      이체 PIN {PIN}")
    print(f"  내 계좌     생활비 {living.account_num} (320만원), 월급 {salary.account_num} (150만원)")
    print(f"  수취인      엄마 {mom.account_num}, 집주인 {landlord.account_num}")
    print(f"  시나리오 2  처음 보는 계좌(중고차 판매자) {seller.account_num}")
    print(f"  시나리오 3  사기 '안전계좌'              {scammer.account_num}")
    print("\n  목소리 승인을 쓰려면 설정 화면에서 목소리를 등록하세요 (이미 등록했다면 그대로 남아 있습니다).")


async def run() -> None:
    try:
        await main()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(run(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(run())
