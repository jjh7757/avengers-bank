"""다른 참가 은행의 연동 시험용 수취 계좌 (ClearingHub SPEC "빠른 시작"·9.4에 공개하는 값).

    uv run python scripts/interbank_test_account.py

배포 서버에서는 컨테이너 안에서: docker exec avengers-bank python scripts/interbank_test_account.py

만드는 것 (없을 때만. 여러 번 실행해도 그대로다)
- 고객 테스트수취 (로그인 불가: 비밀번호를 임의 값으로 두고 아무에게도 알려 주지 않는다)
  생년월일 20000101, 휴대폰 010-1111-2222 → 가상 CI. 다른 은행이 같은 값으로 본인 계좌 조회(9.4)를 시험할 수 있다
- 입출금 계좌 110-901-000001 (잔액 0원에서 시작)

다른 은행이 보낸 돈은 이 계좌에 쌓이고 돌려주지 않는다. 시연 데이터(scripts/demo_seed.py)와 따로라 그 스크립트가 지우지 않는다.
"""

import asyncio
import secrets
import selectors
import sys

from sqlalchemy import select, update

from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.security import hash_password
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.schemas import CheckingAccountCreate
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.products.models import AccountProduct
from avengers_bank.domains.products.seed import seed_products
from avengers_bank.domains.users.ci import ci_of
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.schemas import UserResponse
from avengers_bank.knowledge.terms import find_terms

LOGIN_ID = "interbank_test"
NAME = "테스트수취"
BIRTH_DATE = "20000101"
PHONE = "010-1111-2222"
ACCOUNT_NUM = "110-901-000001"
NICKNAME = "타행 연동 시험"


class AccountNumTaken(Exception):
    """시험 계좌번호를 다른 고객이 이미 쓰고 있다 (임의 발급 번호와 겹친 경우)."""


async def ensure_test_account(db) -> CheckingAccount:
    """시험 고객과 계좌가 없으면 만들고, 있으면 그대로 둔다 (잔액·거래내역을 지우지 않는다).
    CI는 실행할 때마다 다시 계산한다 (CI_KEY를 나중에 넣거나 바꿨을 때 맞추려고)."""
    async with db.begin():
        await seed_products(db)
        user = await db.scalar(select(User).where(User.login_id == LOGIN_ID))
        if user is None:
            user = User(login_id=LOGIN_ID, hashed_password=hash_password(secrets.token_urlsafe(32)), name=NAME,
                        phone=PHONE)
            db.add(user)
        user.name, user.phone, user.birth_date = NAME, PHONE, BIRTH_DATE
        user.ci = ci_of(NAME, BIRTH_DATE, PHONE)
        await db.flush()
        await db.refresh(user)
        user_id = user.user_id
        account = await db.scalar(select(CheckingAccount).where(CheckingAccount.account_num == ACCOUNT_NUM))
        if account is not None:
            if account.user_id != user_id:
                raise AccountNumTaken(f"{ACCOUNT_NUM}은(는) 다른 고객의 계좌입니다. 스크립트의 ACCOUNT_NUM을 바꾸세요")
            return account
        product = await db.get(AccountProduct, 1)
        response = UserResponse.model_validate(user)

    # 앱에서 약관에 동의하고 연 것처럼 연다 (동의 기록도 남는다). 번호만 SPEC에 적을 고정 번호로 바꾼다
    detail = await account_service.open_checking(
        db, CheckingAccountCreate(product_id=1, nickname=NICKNAME, terms_version=find_terms(product.name).version),
        response,
    )
    async with db.begin():
        await db.execute(update(CheckingAccount).where(CheckingAccount.checking_account_id == detail.account_id)
                         .values(account_num=ACCOUNT_NUM))
        return await db.get(CheckingAccount, detail.account_id)


async def main() -> None:
    async with SessionLocal() as db:
        account = await ensure_test_account(db)
        ci_set = await db.scalar(select(User.ci).where(User.login_id == LOGIN_ID))
    print("타행 연동 시험 계좌를 준비했습니다.\n")
    print(f"  은행 901 계좌 {account.account_num}  예금주 {NAME}  잔액 {account.balance:,}원")
    print(f"  본인 계좌 조회(9.4) 시험 고객: {NAME} / {BIRTH_DATE} / {PHONE.replace('-', '')}"
          + ("" if ci_set else "  (CI_KEY가 없어 CI를 만들지 못했습니다. 9.4 조회에는 나오지 않습니다)"))


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
