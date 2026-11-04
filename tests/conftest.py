import os

# 앱을 import하기 전에 테스트용 설정을 넣는다 (SQLite 파일 DB).
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-test-secret-key-0000"
os.environ["VOICE_ENCRYPTION_KEY"] = "0nqMmCGBZz4Ii2tmmjnlxxzI5d7Z0r6MWQqv2qD3fWs="  # 테스트 전용 Fernet 키
os.environ["GEMINI_API_KEY"] = ""  # 테스트는 실제 Gemini를 부르지 않는다
os.environ["DEMO_MODE"] = "false"  # 시연 모드는 test_demo.py에서만 켠다

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import avengers_bank.domains.accounts.models  # noqa: F401  모든 테이블을 Base에 등록
import avengers_bank.domains.cards.models  # noqa: F401
import avengers_bank.domains.chat.models  # noqa: F401
import avengers_bank.domains.fds.models  # noqa: F401
import avengers_bank.domains.products.models  # noqa: F401
import avengers_bank.domains.recipients.models  # noqa: F401
import avengers_bank.domains.speech.models  # noqa: F401
from avengers_bank.core.database import Base, SessionLocal, engine
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.chat.confirmation import create_confirmation_token
from avengers_bank.domains.chat.models import ChatSession
from avengers_bank.domains.fds.scorer import Score, fds_scorer
from avengers_bank.domains.products.seed import seed_products
from avengers_bank.main import app

# data/seed/products.json 순서대로 product_id가 1부터 붙는다.
CHECKING_PRODUCT = 1
DEPOSIT_PRODUCT = 2
SAVINGS_PRODUCT = 4
CREDIT_PRODUCT = 1
DEBIT_PRODUCT = 2


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def ml_score(monkeypatch):
    """실제 모델 점수는 실행 시각(심야 여부 등)에 따라 달라지므로 테스트에서는 고정한다.
    test_fds.py처럼 점수를 바꾸고 싶으면 ml_score.value = 0.9 처럼 쓴다."""

    class FixedScore:
        value = 0.01

    monkeypatch.setattr(fds_scorer, "score", lambda features: Score(FixedScore.value, []))
    return FixedScore


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db, db.begin():
        await seed_products(db)
    # 앱 lifespan을 돌려야 MCP 서버(에이전트 도구)가 시작된다
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def signup_and_login(client: AsyncClient, login_id: str, name: str = "테스트") -> dict:
    """회원가입 후 Authorization 헤더를 돌려준다."""
    await client.post(
        "/users/signup",
        json={"login_id": login_id, "password": "password1234", "name": name, "phone": "010-0000-0000"},
    )
    response = await client.post(
        "/users/login", json={"login_id": login_id, "password": "password1234"}
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


async def open_checking(client: AsyncClient, headers: dict, balance: int = 0, **extra) -> dict:
    """입출금 계좌를 열고, API로는 입금할 방법이 없으므로 잔액은 DB에 직접 넣는다."""
    response = await client.post(
        "/accounts/checking", headers=headers, json={"product_id": CHECKING_PRODUCT, **extra}
    )
    assert response.status_code == 201, response.text
    account = response.json()["data"]
    if balance:
        await set_balance(account["account_id"], balance)
        account["balance"] = balance
    return account


async def set_balance(checking_account_id: int, balance: int) -> None:
    async with SessionLocal() as db, db.begin():
        await db.execute(
            update(CheckingAccount)
            .where(CheckingAccount.checking_account_id == checking_account_id)
            .values(balance=balance)
        )


async def new_chat_session(client: AsyncClient, headers: dict) -> str:
    response = await client.post("/chat/sessions", headers=headers)
    assert response.status_code == 201
    return response.json()["data"]["session_id"]


async def confirmed(body: dict, session_id: str, user_id: int = 1) -> dict:
    """에이전트 확인 카드를 거친 것처럼 승인 토큰을 만들어 이체 요청 body에 붙인다."""
    token, jti, _ = create_confirmation_token(
        user_id=user_id,
        session_id=session_id,
        from_checking_account_id=body["from_checking_account_id"],
        to_account_num=body["to_account_num"],
        amount=body["amount"],
    )
    async with SessionLocal() as db, db.begin():
        session = await db.get(ChatSession, session_id)
        session.state = {**session.state, "confirmation_jti": jti}
    return {**body, "session_id": session_id, "confirmation_token": token}


@pytest.fixture
async def user(client):
    return await signup_and_login(client, "ironman", "토니 스타크")


@pytest.fixture
async def other_user(client):
    return await signup_and_login(client, "hulk", "브루스 배너")
