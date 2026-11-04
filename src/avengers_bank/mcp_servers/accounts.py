"""계좌 MCP 서버: 조회, 개설, 별칭 변경, 이체 한도 낮추기"""

from typing import Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from avengers_bank.core.exceptions import BadRequestException
from avengers_bank.domains.accounts.schemas import (
    AccountUpdate,
    CheckingAccountCreate,
    DepositAccountCreate,
    SavingsAccountCreate,
)
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.mcp_servers.common import bank_tool, mask, new_server

AccountType = Literal["checking", "deposit", "savings"]
READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

server = new_server(
    "avengers-accounts",
    "AvengersBank 계좌: 내 입출금·예금·적금 계좌 조회, 거래내역, 계좌 개설, 별칭 변경, 이체 한도 낮추기. "
    "계좌번호는 뒤 4자리만 돌려준다. 바꾸는 도구는 사용자가 대화에서 동의한 뒤에만 호출한다.",
)


def summary(account) -> dict:
    data = account.model_dump(mode="json")
    data["account_num"] = mask(account.account_num)
    return data


@bank_tool(server, annotations=READ)
async def get_my_accounts(db, user) -> dict:
    """내 계좌 목록(입출금·예금·적금)과 잔액"""
    return {"accounts": [summary(a) for a in await account_service.get_my_accounts(db, user)]}


@bank_tool(server, annotations=READ)
async def get_account(db, user, account_type: AccountType, account_id: int) -> dict:
    """계좌 하나의 상세 (한도, 만기일, 월 납입액 등)"""
    return summary(await account_service.get_account(db, account_type, account_id, user))


@bank_tool(server, annotations=READ)
async def get_account_histories(
    db, user, account_type: AccountType, account_id: int, limit: int = Field(default=10, ge=1, le=50)
) -> dict:
    """계좌의 최근 거래내역 (금액: 입금 +, 출금 -)"""
    histories = await account_service.get_histories(db, account_type, account_id, user)
    return {"histories": [h.model_dump(mode="json", include={"date", "amount", "type"}) for h in histories[:limit]]}


@bank_tool(server, annotations=WRITE)
async def open_checking_account(db, user, product_id: int, nickname: str | None = None) -> dict:
    """입출금 계좌 개설. 사용자가 대화에서 개설에 동의한 뒤에만 호출한다. 이체 한도는 기본값(1회 500만, 1일 1,000만)"""
    return summary(await account_service.open_checking(db, CheckingAccountCreate(product_id=product_id, nickname=nickname), user))


@bank_tool(server, annotations=WRITE)
async def open_deposit_account(
    db, user, product_id: int, term_months: int = Field(ge=1, le=60), nickname: str | None = None
) -> dict:
    """예금 계좌 개설. 사용자가 동의한 뒤에만 호출한다. 잔액 0원으로 열리고 입금은 앱에서 한다"""
    data = DepositAccountCreate(product_id=product_id, term_months=term_months, nickname=nickname)
    return summary(await account_service.open_deposit(db, data, user))


@bank_tool(server, annotations=WRITE)
async def open_savings_account(
    db,
    user,
    product_id: int,
    term_months: int = Field(ge=1, le=60),
    monthly_payment: int = Field(gt=0),
    monthly_deposit_date: int = Field(ge=1, le=31),
    nickname: str | None = None,
) -> dict:
    """적금 계좌 개설. 사용자가 동의한 뒤에만 호출한다"""
    data = SavingsAccountCreate(
        product_id=product_id, term_months=term_months, monthly_payment=monthly_payment,
        monthly_deposit_date=monthly_deposit_date, nickname=nickname,
    )
    return summary(await account_service.open_savings(db, data, user))


@bank_tool(server, annotations=WRITE)
async def rename_account(db, user, account_type: AccountType, account_id: int, nickname: str = Field(max_length=50)) -> dict:
    """계좌 별칭 변경. 사용자가 동의한 뒤에만 호출한다"""
    data = AccountUpdate(nickname=nickname)
    return summary(await account_service.update_account(db, account_type, account_id, data, user))


@bank_tool(server, annotations=WRITE)
async def lower_transfer_limits(
    db,
    user,
    checking_account_id: int,
    per_transfer_limit: int | None = Field(default=None, gt=0),
    daily_transfer_limit: int | None = Field(default=None, gt=0),
) -> dict:
    """입출금 계좌 이체 한도를 낮춘다 (높이기는 앱 화면에서만: 탈취·보이스피싱 때 한도를 올려 빼 가는 것을 막기 위해)"""
    current = await account_service.get_account(db, "checking", checking_account_id, user)
    for name, value in (("per_transfer_limit", per_transfer_limit), ("daily_transfer_limit", daily_transfer_limit)):
        if value is not None and value > getattr(current, name):
            raise BadRequestException(
                code="LIMIT_RAISE_NOT_ALLOWED", message="대화로는 이체 한도를 낮추기만 할 수 있어요. 높이기는 앱의 계좌 화면에서 해 주세요."
            )
    changes = {k: v for k, v in {"per_transfer_limit": per_transfer_limit, "daily_transfer_limit": daily_transfer_limit}.items() if v is not None}
    return summary(await account_service.update_account(db, "checking", checking_account_id, AccountUpdate(**changes), user))
