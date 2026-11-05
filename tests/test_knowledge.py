"""knowledge MCP 서버와 약관·FAQ 검색. 테스트는 실제 Gemini를 부르지 않는다 (키가 비어 있어 키워드 검색)."""

import json
from pathlib import Path

import numpy as np
import pytest

from avengers_bank.agents.mcp_client import BankMcpClient
from avengers_bank.knowledge.index import DOCS_DIR, KnowledgeIndex, load_chunks
from tests.test_mcp import user_id

pytestmark = pytest.mark.anyio

SEED = Path(__file__).resolve().parents[1] / "data" / "seed" / "products.json"


def test_every_product_has_terms():
    """상품 시드의 모든 상품에 약관 문서가 있다 (이름이 바뀌면 문서도 고쳐야 한다)"""
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    titles = {chunk.document for chunk in load_chunks()}
    for product in seed["account_products"] + seed["card_products"]:
        assert any(product["name"] in title for title in titles), product["name"]


def test_chunks_are_small_and_readme_is_skipped():
    chunks = load_chunks()
    assert all(chunk.source != "README.md" for chunk in chunks)
    assert all(chunk.section and 0 < len(chunk.text) < 600 for chunk in chunks)
    assert len({chunk.source for chunk in chunks}) == len([p for p in DOCS_DIR.rglob("*.md") if p.name != "README.md"])


async def test_search_terms_tool_keyword_fallback(client, user):
    mcp = BankMcpClient(await user_id(client, user))
    result = await mcp.call("knowledge", "search_terms", {"question": "청년도약적금 가입 나이"})
    assert result["method"] == "keyword"
    assert result["results"][0]["document"].startswith("토르 청년도약적금")
    assert "가입 대상" in [r["section"] for r in result["results"]]
    assert "answer_rule" in result


async def test_list_documents(client, user):
    mcp = BankMcpClient(await user_id(client, user))
    documents = (await mcp.call("knowledge", "list_documents", {}))["documents"]
    assert {"faq/security.md", "products/savings_thor.md"} <= {d["source"] for d in documents}


def fake_vector(text: str) -> list[float]:
    """"해지"가 있으면 한쪽, 없으면 다른 쪽을 가리키는 벡터"""
    return [1.0, 0.0] if "해지" in text else [0.0, 1.0]


async def test_embedding_search_ranks_by_cosine():
    index = KnowledgeIndex()

    async def embed_documents(texts):
        return [fake_vector(t) for t in texts]

    async def embed_query(text):
        return fake_vector(text)

    index.embed_documents, index.embed_query = embed_documents, embed_query
    method, hits = await index.search("만기 전에 그만두면?해지", top_k=3)
    assert method == "embedding"
    assert all("해지" in chunk.embed_text() for chunk, _ in hits)
    assert hits[0][1] == pytest.approx(1.0)


async def test_embedding_failure_falls_back_and_waits_before_retry():
    index = KnowledgeIndex()
    calls = 0

    async def broken(texts):
        nonlocal calls
        calls += 1
        raise RuntimeError("Gemini 503")

    index.embed_documents = broken
    method, hits = await index.search("체크카드 연회비")
    assert method == "keyword" and hits
    method, _ = await index.search("체크카드 연회비")
    assert method == "keyword" and calls == 1  # 실패 직후에는 다시 부르지 않는다


async def test_no_api_key_uses_keyword():
    index = KnowledgeIndex()
    method, hits = await index.search("보이스피싱 경찰 안전계좌")
    assert method == "keyword"
    assert hits[0][0].source == "faq/security.md"
    assert isinstance(hits[0][1], float) and not np.isnan(hits[0][1])
