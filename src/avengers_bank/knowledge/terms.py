"""상품 이용약관: data/knowledge/products/*.md (상담 검색과 같은 문서).

문서 제목("# 캡틴 꾸준적금 약관 요약")에 상품 이름이 들어 있는 문서가 그 상품의 약관이다.
버전 = 파일 내용 해시 앞 12자리. 문서를 고치면 버전이 바뀌어, 예전 버전에 동의한 가입 요청은 거절된다
(화면이 새 약관을 다시 받아 보여 주고 다시 동의받아야 한다).
"""

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from avengers_bank.knowledge.index import DOCS_DIR, load_chunks

PRODUCT_TERMS_DIR = DOCS_DIR / "products"


@dataclass(frozen=True)
class TermsSection:
    title: str
    text: str


@dataclass(frozen=True)
class ProductTerms:
    title: str
    version: str
    source: str
    sections: tuple[TermsSection, ...]


@lru_cache
def _all_terms(docs_dir: Path = PRODUCT_TERMS_DIR) -> tuple[ProductTerms, ...]:
    all_chunks = load_chunks(docs_dir)
    terms = []
    for path in sorted(docs_dir.glob("*.md")):
        chunks = [c for c in all_chunks if c.source == path.name]
        if not chunks:
            continue
        # 줄바꿈을 맞춰야 Windows(CRLF 체크아웃)와 배포 서버(LF)의 버전이 같다
        version = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]
        terms.append(ProductTerms(
            title=chunks[0].document, version=version, source=f"products/{path.name}",
            sections=tuple(TermsSection(c.section, c.text) for c in chunks),
        ))
    return tuple(terms)


def find_terms(product_name: str) -> ProductTerms | None:
    return next((t for t in _all_terms() if product_name in t.title), None)
