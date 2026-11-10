"""관리자 계정 도구. 관리자는 회원가입으로 만들 수 없고 서버에서 이것으로만 만든다.

    python -m avengers_bank.domains.admin.cli create-admin <login_id> --name 관리자 --phone 010-0000-0000
    python -m avengers_bank.domains.admin.cli revoke-admin <login_id>     # 고객(CUSTOMER)으로 강등. 바로 막힌다
    python -m avengers_bank.domains.admin.cli list-admins

비밀번호는 터미널이면 getpass로 두 번 묻고, 터미널이 아니면(스크립트·CI) 환경변수 ADMIN_PASSWORD에서 읽는다 (8자 이상).
운영: docker exec -it avengers-bank python -m avengers_bank.domains.admin.cli create-admin ...
"""

import argparse
import asyncio
import getpass
import os
import selectors
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.security import hash_password
from avengers_bank.domains.users.ci import ci_of
from avengers_bank.domains.users.models import User, UserRole
from avengers_bank.domains.users.repository import user_repository

MIN_PASSWORD = 8


class AdminCliError(Exception):
    pass


async def create_admin(db: AsyncSession, login_id: str, name: str, phone: str, password: str) -> User:
    """새 관리자 계정. 이미 있는 아이디(고객 포함)는 거절한다: 고객 계정을 관리자로 올리지 않고 따로 만든다."""
    if not 4 <= len(login_id) <= 50:
        raise AdminCliError("아이디는 4~50자입니다.")
    if len(password) < MIN_PASSWORD:
        raise AdminCliError(f"비밀번호는 {MIN_PASSWORD}자 이상입니다.")
    if not name or not 9 <= len(phone) <= 20:
        raise AdminCliError("이름과 전화번호(9~20자)가 필요합니다.")
    hashed = await run_in_threadpool(hash_password, password)
    async with db.begin():
        if await user_repository.find_by_login_id(db, login_id) is not None:
            raise AdminCliError(f"이미 있는 아이디입니다: {login_id}")
        user = User(login_id=login_id, hashed_password=hashed, name=name, phone=phone,
                    ci=ci_of(name, None, phone), role=UserRole.ADMIN)
        db.add(user)
    return user


async def revoke_admin(db: AsyncSession, login_id: str) -> User:
    """관리자 → 고객. 역할은 매 요청 DB에서 읽으므로 이미 발급한 토큰으로도 바로 403이다."""
    async with db.begin():
        user = await user_repository.find_by_login_id(db, login_id)
        if user is None:
            raise AdminCliError(f"없는 아이디입니다: {login_id}")
        if user.role != UserRole.ADMIN:
            raise AdminCliError(f"관리자가 아닙니다: {login_id}")
        user.role = UserRole.CUSTOMER
    return user


async def list_admins(db: AsyncSession) -> list[User]:
    async with db.begin():
        return list((await db.scalars(select(User).where(User.role == UserRole.ADMIN).order_by(User.user_id))).all())


def read_password() -> str:
    # ADMIN_PASSWORD가 있으면 먼저 쓴다. Windows에서는 입력을 NUL로 돌려도 isatty()가 True라
    # 터미널 검사만으로 고르면 getpass에서 입력을 기다리며 멈춘다
    password = os.environ.get("ADMIN_PASSWORD", "")
    if password:
        return password
    if sys.stdin.isatty():
        password = getpass.getpass("비밀번호: ")
        if getpass.getpass("비밀번호 확인: ") != password:
            raise AdminCliError("비밀번호가 서로 다릅니다.")
        return password
    raise AdminCliError("터미널이 아니면 환경변수 ADMIN_PASSWORD로 비밀번호를 넘겨 주세요 (docker exec -it로 실행하면 묻습니다).")


async def main(argv: list[str]) -> int:
    from avengers_bank.core.database import SessionLocal, engine

    parser = argparse.ArgumentParser(prog="python -m avengers_bank.domains.admin.cli", description="관리자 계정 관리")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create-admin", help="관리자 계정 만들기 (비밀번호는 묻거나 ADMIN_PASSWORD)")
    c.add_argument("login_id")
    c.add_argument("--name", required=True)
    c.add_argument("--phone", required=True)
    r = sub.add_parser("revoke-admin", help="관리자를 고객으로 강등")
    r.add_argument("login_id")
    sub.add_parser("list-admins", help="관리자 목록")
    args = parser.parse_args(argv)
    try:
        async with SessionLocal() as db:
            if args.command == "create-admin":
                user = await create_admin(db, args.login_id, args.name, args.phone, read_password())
                print(f"관리자를 만들었습니다: #{user.user_id} {user.login_id} ({user.name})")
            elif args.command == "revoke-admin":
                user = await revoke_admin(db, args.login_id)
                print(f"고객으로 강등했습니다: #{user.user_id} {user.login_id}")
            else:
                admins = await list_admins(db)
                for user in admins:
                    print(f"#{user.user_id} {user.login_id} {user.name} {user.phone} (가입 {user.created_at:%Y-%m-%d})")
                if not admins:
                    print("관리자 없음")
    except AdminCliError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    loop_factory = (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) if sys.platform == "win32" else None
    sys.exit(asyncio.run(main(sys.argv[1:]), loop_factory=loop_factory))
