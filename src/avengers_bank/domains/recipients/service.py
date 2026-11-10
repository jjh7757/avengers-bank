from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.recipients.models import Recipient
from avengers_bank.domains.recipients.repository import recipient_repository
from avengers_bank.domains.recipients.schemas import RecipientCreate, RecipientUpdate
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import UserResponse

# 이체가 성공해도 수취인을 자동 등록하지 않는다. 별칭은 사용자가 직접 붙여야 하고,
# FDS의 "신규 수취인" 판정이 사용자가 확인한 목록을 기준으로 하도록 하기 위해서다.
# 등록된 수취인에게 보내면 last_sent_at만 갱신한다 (transfers.service).


class RecipientService:
    async def get_my_recipients(
        self, db: AsyncSession, current_user: UserResponse, nickname: str | None = None
    ) -> list[Recipient]:
        async with db.begin():
            if nickname is not None:
                recipient = await recipient_repository.find_by_nickname(
                    db, current_user.user_id, nickname
                )
                return [recipient] if recipient else []
            return await recipient_repository.find_all_by_user_id(db, current_user.user_id)

    async def find_by_nickname(
        self, db: AsyncSession, current_user: UserResponse, nickname: str
    ) -> Recipient:
        """에이전트의 find_recipient 도구가 쓴다. 별칭 → 계좌번호."""
        async with db.begin():
            recipient = await recipient_repository.find_by_nickname(db, current_user.user_id, nickname)
            if recipient is None:
                raise NotFoundException(
                    code="RECIPIENT_NOT_FOUND", message=f'"{nickname}"(으)로 등록된 사람이 없어요.'
                )
            return recipient

    async def create(
        self, db: AsyncSession, data: RecipientCreate, current_user: UserResponse
    ) -> Recipient:
        async with db.begin():
            account = await account_repository.find_checking_by_account_num(db, data.account_num)
            if account is None:
                raise NotFoundException(code="ACCOUNT_NOT_FOUND", message="계좌를 찾을 수 없습니다.")
            # 하이픈 없이 입력했어도 저장·중복 검사는 실제 계좌번호 모양으로 한다
            if await recipient_repository.find_by_account_num(db, current_user.user_id, account.account_num):
                raise ConflictException(
                    code="RECIPIENT_ALREADY_EXISTS", message="이미 등록된 계좌입니다."
                )
            await self._check_nickname_free(db, current_user.user_id, data.nickname)

            holder = await user_repository.find_by_id(db, account.user_id)
            recipient = Recipient(
                user_id=current_user.user_id,
                account_num=account.account_num,
                holder_name=holder.name,
                nickname=data.nickname,
            )
            await recipient_repository.save(db, recipient)
            await db.refresh(recipient)
            return recipient

    async def update(
        self, db: AsyncSession, recipient_id: int, data: RecipientUpdate, current_user: UserResponse
    ) -> Recipient:
        async with db.begin():
            recipient = await self._get_owned(db, recipient_id, current_user.user_id)
            if data.nickname != recipient.nickname:
                await self._check_nickname_free(db, current_user.user_id, data.nickname)
                recipient.nickname = data.nickname
                await db.flush()
            return recipient

    async def delete(self, db: AsyncSession, recipient_id: int, current_user: UserResponse) -> None:
        async with db.begin():
            recipient = await self._get_owned(db, recipient_id, current_user.user_id)
            await recipient_repository.delete(db, recipient)

    async def _get_owned(self, db: AsyncSession, recipient_id: int, user_id: int) -> Recipient:
        recipient = await recipient_repository.find_by_id(db, recipient_id)
        if recipient is None:
            raise NotFoundException(code="RECIPIENT_NOT_FOUND", message="수취인을 찾을 수 없습니다.")
        if recipient.user_id != user_id:
            raise ForbiddenException(code="RECIPIENT_FORBIDDEN", message="본인이 등록한 수취인이 아닙니다.")
        return recipient

    async def _check_nickname_free(self, db: AsyncSession, user_id: int, nickname: str) -> None:
        if await recipient_repository.find_by_nickname(db, user_id, nickname):
            raise ConflictException(
                code="RECIPIENT_NICKNAME_EXISTS", message="같은 이름으로 등록된 수취인이 있습니다."
            )


recipient_service = RecipientService()
