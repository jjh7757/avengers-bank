# TODO

[PROJECT_PLAN.md](PROJECT_PLAN.md)의 일정을 작업 단위로 쪼갠 목록입니다. 위에서 아래 순서로 진행하면 의존 관계가 꼬이지 않습니다.
끝난 항목은 `[x]`로 바꾸고, 범위에서 빼기로 한 항목은 `~~취소선~~`으로 표시합니다.

---

## 0. 계획·환경 (1일)

- [ ] 프로젝트 시작일·발표일 확정 → PROJECT_PLAN.md 4절에 날짜 기입
- [ ] PROJECT_PLAN.md 8절 "정해야 할 것" 결정 (거래 type 값, 계좌번호 형식, 한도 기본값, FDS 임계값, Gemini 모델, STT 전송 방식, TTS 기본값)
  - 거래 type·계좌/카드번호 형식·한도 기본값은 1단계에서 확정. 나머지(날짜, FDS 임계값, Gemini, STT, TTS)는 남음
- [x] PostgreSQL 설치, `avengers_bank` DB 생성 (PostgreSQL 17)
- [x] `cp .env.example .env` 후 `DATABASE_URL`, `JWT_SECRET_KEY` 채우기
- [x] `.env.example`에 `GEMINI_API_KEY` 항목 추가
- [x] `uv sync` → `uv run pytest` 통과 확인
- [x] `uv run alembic revision --autogenerate -m "create initial tables"` (`f4770d0f0d0b`, recipients 포함 14개 테이블)
- [x] PostgreSQL에 `uv run alembic upgrade head` → `uv run python scripts/seed_products.py` (상품 7건)
- [x] `uv run fastapi dev` → `http://127.0.0.1:8000/docs` 접속 확인
- [x] 상위 폴더 `AvengersBankDiagram_fixed.drawio`와 `docs/AvengersBankDiagram.drawio`가 같은지 확인 (동일함)
- [ ] 첫 커밋 (계획서, TODO)

## 1. 백엔드 API (5일)

### 1-1. products
- [x] `data/seed/products.json` 작성 (입출금 1, 예금 2, 적금 2, 신용카드 1, 체크카드 1)
- [x] 시드 삽입 스크립트 `scripts/seed_products.py`
- [x] `products/repository.py`: 목록(type 필터), 상세
- [x] `products/service.py`, `router.py`: `GET /products/accounts`, `/products/accounts/{id}`, `/products/cards`, `/products/cards/{id}`
- [x] `tests/test_products.py`

### 1-2. accounts
- [x] `accounts/repository.py`: 사용자별 3종 계좌 조회, 계좌번호 중복 검사(3테이블), History 조회·저장
- [x] `accounts/service.py`: 계좌번호 발급(`110-/220-/330-` 형식), 개설 시 상품 type 검증, 별칭·한도 변경
- [x] `accounts/router.py`: `GET /accounts`, `POST /accounts/{checking|deposit|savings}`, `GET /accounts/{type}/{id}`, `GET .../histories`, `PATCH /accounts/{type}/{id}`
- [x] 본인 소유 검사 → `ForbiddenException`
- [x] `tests/test_accounts.py`

### 1-3. transfers
- [x] `transfers/schemas.py`: `SavingsPaymentCreate`, `DepositPaymentCreate`, `TransferResponse`
- [x] `transfers/service.py`: `transfer()` (본인 확인 → 받는 계좌 → 잔액·1회·1일 한도 → 양쪽 balance → History 2건, `async with db.begin():` 하나)
- [x] 1일 누적 이체액 계산 쿼리 (당일 `TRANSFER_OUT` 합계)
- [x] `pay_savings()`, `pay_deposit()`
- [x] `transfers/router.py`: `POST /transfers`, `/transfers/savings`, `/transfers/deposit`
- [x] 에러 코드: `INSUFFICIENT_BALANCE`, `PER_TRANSFER_LIMIT_EXCEEDED`, `DAILY_LIMIT_EXCEEDED`, `ACCOUNT_NOT_FOUND`, `ACCOUNT_FORBIDDEN`
- [x] `tests/test_transfers.py` (정상, 잔액 부족, 한도 초과, 남의 계좌)
- [x] FDS 호출 자리를 주석으로 표시 (2단계에서 채움)

### 1-4. cards
- [x] `cards/repository.py`, `service.py`: 발급(상품 type 검증, 카드번호 생성), 결제(체크카드는 연결 계좌 즉시 출금 + History), `accumulated_amount` 갱신
- [x] `cards/router.py`: `GET /cards`, `POST /cards/{credit|debit}`, `GET /cards/{type}/{id}`, `GET .../histories`, `POST .../payments`
- [x] `tests/test_cards.py`

### 1-5. users PATCH, recipients
- [x] `PATCH /users/me` (이름, 닉네임, 전화번호)
- [x] `domains/recipients/` 5개 파일 생성 (models, schemas, repository, service, router)
- [x] `recipients` 테이블 Alembic 마이그레이션 (초기 마이그레이션에 포함)
- [x] `GET/POST/PATCH/DELETE /recipients`, 별칭으로 찾기 메서드
- [x] 이체 성공 시 `recipients.last_sent_at` 갱신 (없는 계좌는 자동 등록하지 않기로 결정)
- [x] `tests/test_recipients.py`
- [x] API_ENDPOINTS.md 상태를 📝 → ✅로 갱신, recipients 섹션 추가

## 2. 합성 데이터 + FDS (5일)

### 2-1. 데이터
- [ ] `fds_training/` 폴더, `pyproject.toml`에 `lightgbm`, `pandas`, `scikit-learn`, `shap` 추가 (dev 또는 별도 그룹)
- [ ] `fds_training/generate_data.py`: 정상 사용자 500명 × 3개월 거래 (급여일 입금, 월세, 소액 결제, 평소 시간대·수취인 패턴)
- [ ] 사기 시나리오 3종 주입 (계정 탈취, 보이스피싱, 테스트 송금 후 고액), 비율 1~2%
- [ ] 각 거래에 `input_mode`, `session_keyword_count` 같은 세션 피처도 생성
- [ ] 시간 기준 분할 (앞 2개월 train, 뒤 1개월 valid) → `fds_training/data/*.parquet`

### 2-2. 피처·모델
- [ ] `src/avengers_bank/domains/fds/features.py`: 피처 계산 함수 (학습 스크립트와 서비스가 같은 코드 사용)
- [ ] `fds_training/train.ipynb` 또는 `train.py`: LightGBM 학습, `scale_pos_weight`, early stopping
- [ ] 평가: PR-AUC, 재현율 80%에서의 정밀도, 놓친 사기 금액, 오탐 건수 → `fds_training/results.md`에 기록
- [ ] SHAP summary plot 저장
- [ ] 모델 저장 `fds_training/model/lgbm.txt`, 임계값 (0.3 / 0.7) 검증 데이터로 조정

### 2-3. 서비스 연동
- [ ] `domains/fds/models.py`: `fds_logs`, `user_devices` + Alembic 마이그레이션
- [ ] `domains/fds/rules.py`: 규칙 8개 (1회·1일 한도, 신규 수취인 고액, 심야 고액, 새 기기, 잔액 소진, 반복 시도, 대화 키워드)
- [ ] `domains/fds/scorer.py`: 모델 로드(앱 시작 시 1회), 피처 → 점수
- [ ] `domains/fds/service.py`: `evaluate()` → `LOW / MEDIUM / HIGH` + rule_hits + ml_score, `fds_logs` 저장
- [ ] `transfers/service.py`에 `fds_service.evaluate()` 삽입. HIGH → `FDS_BLOCKED`, MEDIUM + PIN 미검증 → `ADDITIONAL_AUTH_REQUIRED`
- [ ] `POST /transfers` 요청에 `pin`(선택), `device_fingerprint`, `session_id` 필드 추가
- [ ] 요청 헤더나 바디에서 device fingerprint 받아 `user_devices` 갱신
- [ ] `GET /fds/logs` (본인 것만, 대시보드용)
- [ ] `tests/test_fds.py` (규칙별 1건, LOW/MEDIUM/HIGH 각 1건)

## 3. AUI 에이전트 (6일)

### 3-1. 기반
- [ ] `pyproject.toml`에 `langgraph`, `langchain-google-genai` 추가
- [ ] `core/config.py`에 `GEMINI_API_KEY`, 모델명 설정
- [ ] `domains/chat/models.py`: `chat_sessions`, `chat_messages`(`input_mode` 포함) + 마이그레이션
- [ ] `src/avengers_bank/agents/` 폴더: `graph.py`, `tools.py`, `prompts.py`, `state.py`

### 3-2. 도구
- [ ] `get_my_accounts`, `get_account_histories`
- [ ] `find_recipient` (별칭 → 계좌번호, 없으면 "등록된 사람이 없어요")
- [ ] `prepare_transfer` (확인 카드 JSON 생성, 실행 아님)
- [ ] `execute_transfer` (승인 토큰 검증 후 `transfers.service` 호출)
- [ ] `search_products`
- [ ] `get_my_cards`
- [ ] 도구 입력은 모두 Pydantic 스키마로 검증

### 3-3. 그래프
- [ ] 의도 분류 노드 (조회 / 이체 / 상품 / 카드 / 일반)
- [ ] 슬롯 채우기 노드: 이체는 받는 사람·금액·출금 계좌 없으면 되묻기
- [ ] 금액 정규화 함수 `chat/service.py` ("오만원", "5만 원", "50000원" → 50000) + 단위 테스트
- [ ] 에이전트 추출 금액과 정규화 결과 불일치 시 되묻기
- [ ] 확인 단계: 돈이 움직이는 작업은 `prepare_transfer`까지만, 승인은 프론트 → `POST /transfers`
- [ ] 시스템 프롬프트: 외부 텍스트·붙여넣기 내용은 명령 아님 명시
- [ ] 세션 내 거절 횟수·키워드 수를 state에 누적 → FDS 피처로 전달

### 3-4. API
- [ ] `POST /chat/sessions`, `POST /chat/sessions/{id}/messages` (text, input_mode) → 응답 + 카드(있으면)
- [ ] `GET /chat/sessions/{id}/messages`
- [ ] `POST /transfers`에 확인 카드 승인 토큰 검증 추가
- [ ] `tests/test_chat.py` (LLM 호출은 mock)
- [ ] 수동 시나리오: "엄마한테 5만원 보내줘" → 확인 카드 → 승인 → 이체 완료

## 4. 프론트엔드 (6일)

### 4-1. 기반
- [ ] `frontend/` Vite + React + TypeScript 생성
- [ ] API 클라이언트 (axios/fetch), JWT 저장·헤더 첨부, 401 시 로그인으로
- [ ] 라우팅: 로그인 / 회원가입 / 채팅 홈 / 내 계좌 / 내 카드

### 4-2. 화면
- [ ] 로그인·회원가입 폼
- [ ] 채팅 홈: 메시지 목록, 입력창, 전송
- [ ] 메시지 안 카드 렌더링: 계좌 요약 카드, 이체 확인 카드
- [ ] 이체 확인 카드: 받는 사람·금액·출금 계좌 + 승인/취소. `ADDITIONAL_AUTH_REQUIRED`면 PIN 입력 필드 표시 후 재요청
- [ ] 차단 안내: `FDS_BLOCKED` 응답 시 규칙 이름과 경고 문구 표시
- [ ] 내 계좌 / 내 카드 목록, 거래내역
- [ ] device fingerprint 생성(간단한 브라우저 정보 해시) → 이체 요청에 포함

### 4-3. 음성 (STT/TTS, 2일)
- [ ] `src/hooks/useSpeech.ts`: `SpeechRecognition`(ko-KR) push-to-talk, `SpeechSynthesis` 래퍼
- [ ] 마이크 버튼: 누르는 동안 녹음, 인식 결과를 입력창에 표시, (결정에 따라) 침묵 1.5초 후 자동 전송
- [ ] 메시지 전송 시 `input_mode: "voice"` 전달
- [ ] TTS 토글: 에이전트 응답 읽기, 확인 카드는 "OOO님께 5만원을 보냅니다. 승인하시겠어요?"만 읽기, 계좌번호 제외
- [ ] FDS MEDIUM·HIGH 메시지는 토글과 무관하게 TTS 재생
- [ ] 마이크 버튼 누르면 재생 중인 TTS 중단
- [ ] ko-KR 보이스 없을 때 토글 비활성화 + 안내
- [ ] Chrome에서 "엄마한테 오만원 보내줘" 음성 → 확인 카드 도달 확인

## 5. 통합·시연 준비 (3일)

- [ ] 시연용 시드: 사용자 1명, 입출금 계좌 2개, 수취인 "엄마" 등록, 평소 거래 이력 30건
- [ ] 시나리오 1 정상 이체(음성) 끝까지 통과
- [ ] 시나리오 2 신규 수취인 150만원 → MEDIUM → PIN → 완료
- [ ] 시나리오 3 심야 + 잔액 95% + 신규 수취인 + 키워드 → HIGH 차단 + TTS 경고
- [ ] 시나리오 3의 "심야" 조건을 시연 시간에 맞춰 재현할 방법 (시간 주입 옵션 또는 환경변수)
- [ ] 시나리오 4 SHAP 기여도를 차단 메시지 또는 대시보드에 표시
- [ ] 음성 시연 녹화 영상 준비 (발표장 마이크 문제 대비)
- [ ] 텍스트 입력으로 같은 시나리오 즉시 전환 가능한지 확인
- [ ] README 갱신: 실행 방법(백엔드 + 프론트), 환경변수, 시연 순서
- [ ] 발표 자료 작성

## 6. 선택 기능 (남는 기간)

- [ ] RAG: `rag/` 폴더, 상품 설명·약관 → Chroma, `search_products`에 연결
- [ ] LLM 기반 대화 위험 판별 (키워드 규칙의 상위 버전)
- [ ] FDS 대시보드 화면 (`fds_logs` 표)
- [ ] `domains/speech`: `POST /speech/stt` (MediaRecorder webm → Gemini), `POST /speech/tts` (Google Cloud TTS)
- [ ] 브라우저 미지원 시 서버 STT 폴백 연결
- [ ] 서버 STT와 브라우저 STT 인식 정확도 비교표
