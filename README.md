# AvengersBank

은행 서비스 백엔드: FastAPI + SQLAlchemy(async) + PostgreSQL + Alembic

## 문서

| 문서 | 내용 |
|---|---|
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | 프로젝트 계획서: 목표, 아키텍처, AUI·FDS 설계, 일정, 리스크 |
| [docs/DEMO.md](docs/DEMO.md) | **시연 대본**: 준비, 시나리오 6개, 비상 대응 |
| [docs/PRESENTATION.md](docs/PRESENTATION.md) | 발표 자료 초안 (슬라이드별) |
| [docs/MCP_SERVERS.md](docs/MCP_SERVERS.md) | MCP 서버 6개, 도구 28개, 안전 규칙, 약관·FAQ 검색(RAG), 가입 시 이용약관 동의 |
| [docs/VOICE_AUTH.md](docs/VOICE_AUTH.md) | 음성 승인(화자 인증) 설계, 측정 결과, 한계 |
| [docs/INTERBANK.md](docs/INTERBANK.md) | 다른 은행 이체: ClearingHub 연동, 돈 흐름, 실패·응답 없음 처리 |
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
| `BANK_CODE`, `HUB_URL`, `HUB_API_KEY`, `HUB_SECRET` | 타행 이체 | [ClearingHub](https://github.com/jjh7757/clearing-hub) 중계 서버가 발급한 은행 코드·키. 셋 중 하나라도 없으면 타행 이체가 꺼진다 ([INTERBANK.md](docs/INTERBANK.md)) |
| `LOG_LEVEL` | | 로그 수준 (기본 `INFO`) |
| `LOG_FORMAT` | | `json`(기본, 한 줄에 JSON 하나) 또는 `text`(로컬에서 읽기 편한 형식) |
| `SENTRY_DSN` | | 넣으면 처리하지 못한 오류를 Sentry로 보낸다. 비우면 아무것도 하지 않음 |
| `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE` | | Sentry 환경 이름(기본 `production`), 성능 추적 비율 0~1(기본 0) |

## 운영·모니터링

- **헬스체크** `GET /health` (운영 컨테이너에서는 `/health`와 `/api/health` 둘 다): DB에 `SELECT 1`까지 보내 확인한다. 정상 200 `{"status": "ok", "checks": {"database": "ok"}}`, DB에 닿지 않거나 3초 넘게 걸리면 503. 인증 없이 부를 수 있고 오류 내용은 응답에 넣지 않는다.
- **요청 ID**: 요청마다 `X-Request-ID`를 정해(받은 값이 영문·숫자·`.`·`_`·`:`·`-` 128자 이내면 그대로, 아니면 새로 만든다) 응답 헤더에 붙인다. 그 요청에서 남긴 로그에도 `request_id`가 붙어서, 사용자가 알려 준 ID로 로그를 바로 찾을 수 있다.
- **구조화 로그**: 표준 출력에 한 줄 JSON (`time`, `level`, `logger`, `message`, `request_id` …). 요청마다 접근 로그 `avengers_bank.access`에 `method`·`path`·`status`·`duration_ms`가 남는다 (헬스체크는 DEBUG). 코드는 [core/logging.py](src/avengers_bank/core/logging.py), [core/health.py](src/avengers_bank/core/health.py), [core/sentry.py](src/avengers_bank/core/sentry.py).
- **Sentry**(선택): `SENTRY_DSN`이 있을 때만 켜진다. 개인정보(요청 본문·쿠키·IP)는 보내지 않고 `request_id` 태그를 붙인다.

```bash
curl -i http://127.0.0.1:8000/health
```

## 테스트

```bash
uv run pytest
```

테스트는 SQLite로 돌아가서 PostgreSQL 없이도 실행됩니다.

화면 E2E 테스트(Playwright: 로그인 → 계좌 → 내 다른 계좌로 이체 → 완료)는 `frontend`에서 `npm run test:e2e`. 테스트 전용 SQLite DB에 시연 데이터를 넣고 서버를 따로 띄웁니다 ([frontend/README.md](frontend/README.md#e2e-테스트)).

### CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml)이 백엔드 `pytest`, 프론트 `tsc -b`·`oxlint`·`build`, E2E를 돌립니다. PR과 다른 브랜치 push에는 검사만, `feature/backend-api` push에는 [`deploy.yml`](.github/workflows/deploy.yml)이 이 검사를 먼저 부르고 **모두 통과해야** 이미지 빌드·배포로 넘어갑니다.

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
| MCP 서버 | ✅ 은행 기능·상담 지식 도구 28개를 서버 6개로, 에이전트는 MCP로만 사용 ([MCP_SERVERS.md](docs/MCP_SERVERS.md)) |
| 상품 가입·이용약관 | ✅ 앱(`/products`)이나 모아가 가져온 가입 화면에서 약관 동의 후 가입. 서버가 약관 버전을 확인하고 동의 기록을 남김 |
| 약관·FAQ 상담 (RAG) | ✅ knowledge MCP 서버, Gemini 임베딩 검색 + 키워드 대체 (`data/knowledge/`) |
| 음성 승인(화자 인증) | ✅ 4-4 구현, 기준값은 실제 목소리로 보정 필요 ([VOICE_AUTH.md](docs/VOICE_AUTH.md)) |
| 타행 이체 (ClearingHub) | ✅ 보내기(`POST /transfers`의 `to_bank`)·받기(`/interbank/*`)·처리 중 확인, 이체 화면(`/transfer`: 받는 은행 선택, 받는 분 확인, 확인 중 표시), 모아 대화("SimBank 110-123-0001로 5만원") ([INTERBANK.md](docs/INTERBANK.md)) |
