# AvengersBank

은행 서비스 백엔드: FastAPI + SQLAlchemy(async) + PostgreSQL + Alembic

## 문서

| 문서 | 내용 |
|---|---|
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | 프로젝트 계획서: 목표, 아키텍처, AUI·FDS 설계, 일정, 리스크 |
| [docs/DEMO.md](docs/DEMO.md) | **시연 대본**: 준비, 시나리오 6개, 비상 대응 |
| [docs/PRESENTATION.md](docs/PRESENTATION.md) | 발표 자료 초안 (슬라이드별) |
| [docs/MCP_SERVERS.md](docs/MCP_SERVERS.md) | MCP 서버 6개, 도구 26개, 안전 규칙, 약관·FAQ 검색(RAG) |
| [docs/VOICE_AUTH.md](docs/VOICE_AUTH.md) | 음성 승인(화자 인증) 설계, 측정 결과, 한계 |
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

화면: http://localhost:5173 (음성 입력은 Chrome·Edge). 첫 화면은 도우미 "모아"가 필요한 화면을 가져오는 화면이고, 채팅 목록은 `/chat`

## 시연

`.env`에 `DEMO_MODE=true`를 넣고 서버를 켠 뒤:

```bash
uv run python scripts/demo_seed.py     # 시연 데이터 만들기·초기화 (demo / demo1234!)
```
```bash
uv run python scripts/demo_check.py    # 시나리오 자동 점검 (실제 Gemini)
```

순서와 비상 대응은 [docs/DEMO.md](docs/DEMO.md).

## 환경변수 (`.env`)

| 이름 | 필수 | 설명 |
|---|---|---|
| `DATABASE_URL`, `JWT_SECRET_KEY` | ✅ | PostgreSQL 주소, JWT 서명 키(32자 이상) |
| `GEMINI_API_KEY` | 채팅 | 없으면 채팅·음성 숫자 인식만 503 |
| `GEMINI_FAST_MODEL`, `GEMINI_CHAT_MODEL` | | 의도 분류용 / 조회·상담 답변용 모델 |
| `VOICE_ENCRYPTION_KEY` | 음성 승인 | 목소리 특징 암호화 Fernet 키. 바꾸면 다시 등록해야 함 |
| `VOICE_SIMILARITY_THRESHOLD` | | 화자 인증 기준 (기본 0.45, 보정 필요) |
| `DEMO_MODE` | | true면 `/demo/clock`으로 업무 시각 옮기기 (발표용 로컬에서만) |

## 테스트

```bash
uv run pytest
```

테스트는 SQLite로 돌아가서 PostgreSQL 없이도 실행됩니다.

음성 승인(화자 인증)을 쓰려면 PyTorch가 든 `voice` 그룹을 함께 설치·실행합니다 (약 1GB). 없으면 승인 버튼 + PIN으로만 동작합니다.

```bash
uv sync --group voice
uv run --group voice fastapi dev
```

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
| MCP 서버 | ✅ 은행 기능·상담 지식 도구 26개를 서버 6개로, 에이전트는 MCP로만 사용 ([MCP_SERVERS.md](docs/MCP_SERVERS.md)) |
| 약관·FAQ 상담 (RAG) | ✅ knowledge MCP 서버, Gemini 임베딩 검색 + 키워드 대체 (`data/knowledge/`) |
| 음성 승인(화자 인증) | ✅ 4-4 구현, 기준값은 실제 목소리로 보정 필요 ([VOICE_AUTH.md](docs/VOICE_AUTH.md)) |
