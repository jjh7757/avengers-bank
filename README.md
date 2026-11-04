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

`.env`에 `DATABASE_URL`과 `JWT_SECRET_KEY`(32자 이상)를 채웁니다. 채팅 에이전트를 쓰려면 `GEMINI_API_KEY`도 필요합니다 (없으면 채팅 API만 503).

```bash
uv run alembic upgrade head
uv run python scripts/seed_products.py
uv run fastapi dev
```

API 문서: http://127.0.0.1:8000/docs

프론트엔드는 다른 터미널에서 실행합니다 (Node 24 이상).

```bash
cd frontend
npm install
npm run dev
```

화면: http://localhost:5173 (음성 입력은 Chrome·Edge)

## 테스트

```bash
uv run pytest
```

테스트는 SQLite로 돌아가서 PostgreSQL 없이도 실행됩니다.

> Windows에서는 `uv run fastapi run`이 psycopg 비동기 모드와 맞지 않아 DB 연결에 실패합니다. 개발 중에는 `fastapi dev`를 쓰세요.

## FDS 모델 다시 학습하기

학습용 패키지는 `fds` 그룹에 있습니다. 학습된 모델(`fds_training/model/`)은 저장소에 포함되어 있어서 서버 실행에는 필요 없습니다.

```bash
uv run --group fds python fds_training/generate_data.py   # 합성 데이터 → fds_training/data/ (git 제외)
uv run --group fds python fds_training/train.py           # 모델·임계값·results.md·SHAP 그림
```

## 현재 상태

| 도메인 | 상태 |
|---|---|
| users, products, accounts, transfers, cards, recipients | ✅ 1단계 백엔드 API 완료 ([API_ENDPOINTS.md](docs/API_ENDPOINTS.md)) |
| fds | ✅ 2단계 규칙 엔진 + LightGBM, 이체에 연결 ([results.md](fds_training/results.md)) |
| chat(에이전트) | ✅ 3단계 LangGraph + Gemini, 확인 카드 승인 후 이체 |
| frontend | ✅ 4단계 채팅·확인 카드·FDS 안내·계좌·카드·음성 입력/안내 ([frontend/README.md](frontend/README.md)) |
| 음성 승인(화자 인증) | 📝 [TODO.md](docs/TODO.md) 4-4 |
