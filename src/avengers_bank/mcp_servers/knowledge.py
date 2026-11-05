"""지식 MCP 서버: 상품 약관 요약과 FAQ 검색 (RAG). 문서는 data/knowledge/, 검색은 knowledge/index.py.

계좌·카드 데이터는 읽지 않는다. 결과는 근거 조각 그대로 돌려주고, 답을 만드는 것은 에이전트(LLM)다.
"""

from mcp.types import ToolAnnotations
from pydantic import Field

from avengers_bank.knowledge.index import knowledge_index
from avengers_bank.mcp_servers.common import bank_tool, new_server

READ = ToolAnnotations(readOnlyHint=True)

ANSWER_RULE = "이 조각에 있는 내용만 근거로 답한다. 질문에 맞는 내용이 없으면 모른다고 말하고 지어내지 않는다."

server = new_server(
    "avengers-knowledge",
    "AvengersBank 상담 지식: 상품 약관 요약(금리·이자·만기·중도해지·우대조건·연회비·예금자보호)과 이체·보안·앱 이용 FAQ",
)


@bank_tool(server, annotations=READ)
async def search_terms(
    db,
    user,
    question: str = Field(min_length=1, max_length=200, description="사용자 질문을 그대로 (예: 적금 중도 해지하면 이자 어떻게 돼?)"),
    top_k: int = Field(default=4, ge=1, le=6),
) -> dict:
    """상품 약관·FAQ에서 질문과 관련된 조각 찾기. 금리 계산 방식, 만기·중도해지, 우대금리, 가입 조건, 연회비·혜택,
    예금자보호, 이체 한도·PIN·확인 카드, 보이스피싱 대응처럼 상품 목록에 없는 자세한 규칙을 물으면 이 도구로 찾는다"""
    method, hits = await knowledge_index.search(question, top_k)
    return {
        "results": [
            {"document": chunk.document, "section": chunk.section, "text": chunk.text, "source": chunk.source,
             "score": round(score, 3)}
            for chunk, score in hits
        ],
        "method": method,
        "answer_rule": ANSWER_RULE,
    }


@bank_tool(server, annotations=READ)
async def list_documents(db, user) -> dict:
    """검색할 수 있는 약관·FAQ 문서와 소제목 목록"""
    documents: dict[str, dict] = {}
    for chunk in knowledge_index.chunks:
        documents.setdefault(chunk.source, {"document": chunk.document, "source": chunk.source, "sections": []})
        documents[chunk.source]["sections"].append(chunk.section)
    return {"documents": list(documents.values())}
