"""Gemini 호출을 한곳에 모은다. 테스트는 이 모듈의 classify, get_chat_llm을 바꿔 끼운다."""

from functools import lru_cache

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from avengers_bank.agents.prompts import CLASSIFY_PROMPT
from avengers_bank.agents.state import Extraction, PendingTransfer
from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException

CLASSIFY_HISTORY = 6  # 의도 분류에 넣는 직전 대화 수


class LlmUnavailableException(ApiException):
    def __init__(self, message: str = "AI 상담을 잠시 사용할 수 없어요. 잠시 후 다시 시도해 주세요."):
        super().__init__(status_code=503, code="LLM_UNAVAILABLE", message=message)


def _model(name: str) -> ChatGoogleGenerativeAI:
    settings = get_settings()
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value():
        raise LlmUnavailableException("GEMINI_API_KEY가 설정되지 않았습니다.")
    return ChatGoogleGenerativeAI(
        model=name, api_key=settings.gemini_api_key.get_secret_value(), temperature=0, max_retries=2
    )


@lru_cache
def get_fast_llm() -> ChatGoogleGenerativeAI:
    return _model(get_settings().gemini_fast_model)


@lru_cache
def get_chat_llm() -> ChatGoogleGenerativeAI:
    return _model(get_settings().gemini_chat_model)


async def classify(history: list[BaseMessage], user_text: str, pending: PendingTransfer | None) -> Extraction:
    pending_text = pending.model_dump_json(exclude_none=True) if pending else "없음"
    messages = [
        SystemMessage(CLASSIFY_PROMPT.format(pending=pending_text)),
        *history[-CLASSIFY_HISTORY:],
        HumanMessage(user_text),
    ]
    return await get_fast_llm().with_structured_output(Extraction).ainvoke(messages)
