"""상담 지식 검색 (RAG의 검색 부분). knowledge MCP 서버의 search_terms가 쓴다.

문서: data/knowledge/**/*.md. "# 제목" = 문서, "## 소제목" 하나 = 검색 조각 하나.
검색: Gemini 임베딩 + 코사인 유사도 (메모리 안, numpy). 벡터 DB(Chroma)는 쓰지 않는다.
  조각이 수십 개뿐이고, 배포 컨테이너 메모리 상한(512MB) 안에 두기 위해서다.
  문서 임베딩은 처음 검색할 때 한 번 만들어 프로세스 메모리에 둔다.
임베딩을 쓸 수 없으면(키 없음, 호출 실패·지연) 글자 두 개 단위(bigram) 키워드 검색으로 대신한다.
  실패한 뒤에는 RETRY_SECONDS 동안 키워드 검색만 쓰고, 그 뒤에 다시 임베딩을 시도한다.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from avengers_bank.core.config import get_settings

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parents[3] / "data" / "knowledge"
EMBED_DIMENSIONS = 768
TIMEOUT_SECONDS = 10
RETRY_SECONDS = 60


@dataclass(frozen=True)
class Chunk:
    source: str  # data/knowledge 기준 경로 (products/savings_thor.md)
    document: str  # 문서 제목
    section: str  # 소제목
    text: str  # 본문

    def embed_text(self) -> str:
        return f"{self.document} - {self.section}\n{self.text}"


def load_chunks(docs_dir: Path = DOCS_DIR) -> list[Chunk]:
    chunks = []
    for path in sorted(docs_dir.rglob("*.md")):
        if path.name == "README.md":
            continue
        source = path.relative_to(docs_dir).as_posix()
        document, section, lines = path.stem, None, []

        def flush() -> None:
            body = " ".join(line.strip() for line in lines if line.strip())
            if section and body:
                chunks.append(Chunk(source, document, section, body))

        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                flush()
                section, lines = line[3:].strip(), []
            elif line.startswith("# "):
                document = line[2:].strip()
            else:
                lines.append(line)
        flush()
    return chunks


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"[^0-9a-zA-Z가-힣]", "", text).lower()
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def keyword_scores(query: str, chunks: list[Chunk]) -> np.ndarray:
    """질문의 글자 두 개 묶음이 조각에 얼마나 들어 있는지 (0~1). 제목·소제목에 있으면 더 친다."""
    wanted = _bigrams(query)
    if not wanted:
        return np.zeros(len(chunks))
    scores = []
    for chunk in chunks:
        heading, body = _bigrams(f"{chunk.document} {chunk.section}"), _bigrams(chunk.text)
        scores.append((len(wanted & body) + 0.5 * len(wanted & heading)) / (1.5 * len(wanted)))
    return np.array(scores)


class KnowledgeIndex:
    def __init__(self, docs_dir: Path = DOCS_DIR) -> None:
        self.chunks = load_chunks(docs_dir)
        self._vectors: np.ndarray | None = None
        self._lock = asyncio.Lock()
        self._retry_at = 0.0

    def _embeddings(self, task_type: str) -> GoogleGenerativeAIEmbeddings | None:
        settings = get_settings()
        if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value():
            return None
        return GoogleGenerativeAIEmbeddings(
            model=settings.gemini_embedding_model, api_key=settings.gemini_api_key.get_secret_value(),
            task_type=task_type, output_dimensionality=EMBED_DIMENSIONS,
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]] | None:
        """테스트는 이 메서드와 embed_query를 바꿔 끼운다."""
        model = self._embeddings("RETRIEVAL_DOCUMENT")
        return None if model is None else await model.aembed_documents(texts)

    async def embed_query(self, text: str) -> list[float] | None:
        model = self._embeddings("RETRIEVAL_QUERY")
        return None if model is None else await model.aembed_query(text)

    async def _document_vectors(self) -> np.ndarray | None:
        if self._vectors is not None or time.monotonic() < self._retry_at:
            return self._vectors
        async with self._lock:
            if self._vectors is None and time.monotonic() >= self._retry_at:
                vectors = await self.embed_documents([chunk.embed_text() for chunk in self.chunks])
                if vectors is None:
                    self._retry_at = float("inf")  # 키가 없으면 다시 시도하지 않는다
                else:
                    self._vectors = _normalize(np.array(vectors, dtype=np.float32))
        return self._vectors

    async def _embedding_scores(self, query: str) -> np.ndarray | None:
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                vectors = await self._document_vectors()
                if vectors is None:
                    return None
                query_vector = await self.embed_query(query)
        except Exception:
            logger.warning("지식 검색 임베딩 실패, 키워드 검색으로 대신합니다", exc_info=True)
            self._retry_at = time.monotonic() + RETRY_SECONDS
            return None
        if query_vector is None:
            return None
        return vectors @ _normalize(np.array(query_vector, dtype=np.float32))

    async def search(self, query: str, top_k: int = 3) -> tuple[str, list[tuple[Chunk, float]]]:
        """(검색 방법, [(조각, 점수)]) 점수 높은 순. 방법은 "embedding" 또는 "keyword"."""
        scores, method = await self._embedding_scores(query), "embedding"
        if scores is None:
            scores, method = keyword_scores(query, self.chunks), "keyword"
        order = np.argsort(-scores)[:top_k]
        return method, [(self.chunks[i], float(scores[i])) for i in order if scores[i] > 0]


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


knowledge_index = KnowledgeIndex()
