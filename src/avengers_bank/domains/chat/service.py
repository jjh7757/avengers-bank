import logging
import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.agents import ui_context
from avengers_bank.agents.graph import AgentContext, build_graph
from avengers_bank.agents.llm import LlmUnavailableException
from avengers_bank.agents.state import PendingTransfer
from avengers_bank.agents.mcp_client import BankMcpClient
from avengers_bank.core.clock import now_utc
from avengers_bank.core.exceptions import ApiException, ForbiddenException, NotFoundException
from avengers_bank.domains.chat.models import ChatMessage, ChatSession
from avengers_bank.domains.chat.repository import chat_repository
from avengers_bank.domains.chat.schemas import ChatMessageCreate
from avengers_bank.domains.users.schemas import UserResponse

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 12  # 에이전트에 넣는 직전 대화 수


def to_langchain(message: ChatMessage) -> BaseMessage:
    if message.role == "user":
        return HumanMessage(message.content)
    content = message.content
    if message.card and message.card.get("type") == "transfer_confirmation":
        content += " [확인 카드를 보여 줌]"
    return AIMessage(content)


class ChatService:
    async def create_session(self, db: AsyncSession, current_user: UserResponse) -> ChatSession:
        async with db.begin():
            session = ChatSession(session_id=uuid.uuid4().hex, user_id=current_user.user_id, state={})
            await chat_repository.save(db, session)
            await db.refresh(session)
            return session

    async def get_messages(
        self, db: AsyncSession, session_id: str, current_user: UserResponse
    ) -> list[ChatMessage]:
        async with db.begin():
            await self.get_owned_session(db, session_id, current_user.user_id)
            return await chat_repository.find_messages(db, session_id)

    async def send_message(
        self, db: AsyncSession, session_id: str, data: ChatMessageCreate, current_user: UserResponse
    ) -> tuple[ChatMessage, ChatMessage]:
        # 1. 사용자 메시지 저장 (FDS 대화 키워드 규칙이 이 기록을 읽는다)
        async with db.begin():
            session = await self.get_owned_session(db, session_id, current_user.user_id)
            history = [to_langchain(m) for m in await chat_repository.find_messages(db, session_id, HISTORY_LIMIT)]
            pending_raw = (session.state or {}).get("pending_transfer")
            user_message = ChatMessage(
                session_id=session_id, role="user", content=data.text,
                input_mode=data.input_mode, created_at=now_utc(),
            )
            await chat_repository.save(db, user_message)

        # 2. 에이전트 실행. 은행 기능은 MCP 서버의 도구로 쓴다 (도구마다 자기 DB 세션)
        ctx = AgentContext(session_id=session_id, mcp=BankMcpClient(current_user.user_id))
        try:
            result = await build_graph(ctx).ainvoke({
                "user_text": data.text,
                "ui_context": ui_context.describe(data.ui_context),
                "history": history,
                "pending": PendingTransfer.model_validate(pending_raw) if pending_raw else None,
            })
        except ApiException:
            raise
        except Exception as exc:
            logger.exception("에이전트 실행 실패: session=%s", session_id)
            raise LlmUnavailableException() from exc

        # 3. 답변 저장, 대화 상태 갱신
        async with db.begin():
            session = await chat_repository.find_session(db, session_id, for_update=True)
            state = dict(session.state or {})
            new_pending = result.get("new_pending")
            state["pending_transfer"] = new_pending.model_dump() if new_pending else None
            if "confirmation_jti" in result:
                state["confirmation_jti"] = result["confirmation_jti"]
            session.state = state  # JSON 컬럼은 새 dict를 넣어야 변경이 감지된다

            user_message.intent = result["extraction"].intent
            assistant_message = ChatMessage(
                session_id=session_id, role="assistant", content=result["reply"],
                input_mode="text", card=result.get("card"), screen=result.get("screen"),
                screen_params=result.get("screen_params"), created_at=now_utc(),
            )
            await chat_repository.save(db, assistant_message)
            await db.flush()
        return user_message, assistant_message

    async def get_owned_session(
        self, db: AsyncSession, session_id: str, user_id: int, *, for_update: bool = False
    ) -> ChatSession:
        """transfers.service도 이체 확인 토큰을 검사할 때 쓴다 (열린 트랜잭션 안에서)."""
        session = await chat_repository.find_session(db, session_id, for_update=for_update)
        if session is None:
            raise NotFoundException(code="CHAT_SESSION_NOT_FOUND", message="대화를 찾을 수 없습니다.")
        if session.user_id != user_id:
            raise ForbiddenException(code="CHAT_SESSION_FORBIDDEN", message="본인 대화가 아닙니다.")
        return session


chat_service = ChatService()
