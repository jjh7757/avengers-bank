# AvengersBank

은행 서비스 백엔드: FastAPI + SQLAlchemy(async) + PostgreSQL + Alembic

## 문서

| 문서 | 내용 |
|---|---|
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | 프로젝트 계획서: 목표, 아키텍처, AUI·FDS 설계, 일정, 리스크 |
| [docs/TODO.md](docs/TODO.md) | 계획서를 작업 단위로 쪼갠 체크리스트 |
| [docs/ERD.md](docs/ERD.md) | ER 다이어그램 (Mermaid), 코드에서 지킬 규칙 · 원본: [AvengersBankDiagram.drawio](docs/AvengersBankDiagram.drawio) |
| [docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md) | API 엔드포인트 목록, 요청·응답 형식, 구현 상태 |
| [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | 폴더 구조, 계층(router → service → repository) 설명, 역할 분담 |

## 시작하기

[uv](https://docs.astral.sh/uv/)와 PostgreSQL이 필요합니다.

```bash
uv sync
cp .env.example .env
```

`.env`에 `DATABASE_URL`과 `JWT_SECRET_KEY`(32자 이상)를 채웁니다.

```bash
uv run alembic upgrade head
uv run python scripts/seed_products.py
uv run fastapi dev
```

API 문서: http://127.0.0.1:8000/docs

## 테스트

```bash
uv run pytest
```

테스트는 SQLite로 돌아가서 PostgreSQL 없이도 실행됩니다.

## 현재 상태

| 도메인 | 상태 |
|---|---|
| users, products, accounts, transfers, cards, recipients | ✅ 1단계 백엔드 API 완료 ([API_ENDPOINTS.md](docs/API_ENDPOINTS.md)) |
| fds, chat(에이전트), frontend | 📝 [TODO.md](docs/TODO.md) 2단계부터 |
