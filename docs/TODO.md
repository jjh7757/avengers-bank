# TODO

[PROJECT_PLAN.md](PROJECT_PLAN.md)의 일정을 작업 단위로 쪼갠 목록입니다. 위에서 아래 순서로 진행하면 의존 관계가 꼬이지 않습니다.
끝난 항목은 `[x]`로 바꾸고, 범위에서 빼기로 한 항목은 `~~취소선~~`으로 표시합니다.

---

## 0. 계획·환경 (1일)

- [ ] 프로젝트 시작일·발표일 확정 → PROJECT_PLAN.md 4절에 날짜 기입
- [x] PROJECT_PLAN.md 8절 "정해야 할 것" 결정 (거래 type 값, 계좌번호 형식, 한도 기본값, FDS 임계값, Gemini 모델, STT 전송 방식, TTS 기본값)
  - 프로젝트 날짜만 남음
- [x] PostgreSQL 설치, `avengers_bank` DB 생성 (PostgreSQL 17)
- [x] `cp .env.example .env` 후 `DATABASE_URL`, `JWT_SECRET_KEY` 채우기
- [x] `.env.example`에 `GEMINI_API_KEY` 항목 추가
- [x] `uv sync` → `uv run pytest` 통과 확인
- [x] `uv run alembic revision --autogenerate -m "create initial tables"` (`f4770d0f0d0b`, recipients 포함 14개 테이블)
- [x] PostgreSQL에 `uv run alembic upgrade head` → `uv run python scripts/seed_products.py` (상품 7건)
- [x] `uv run fastapi dev` → `http://127.0.0.1:8000/docs` 접속 확인
- [x] 상위 폴더 `AvengersBankDiagram_fixed.drawio`와 `docs/AvengersBankDiagram.drawio`가 같은지 확인 (동일함)
- [x] 첫 커밋 (계획서, TODO) → `feature/backend-api` 브랜치

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
- [x] `fds_training/` 폴더, `pyproject.toml`에 `lightgbm`, `pandas`, `scikit-learn`, `shap` 추가 (dev 또는 별도 그룹)
- [x] `fds_training/generate_data.py`: 정상 사용자 500명 × 3개월 거래 (급여일 입금, 월세, 소액 결제, 평소 시간대·수취인 패턴)
- [x] 사기 시나리오 3종 주입 (계정 탈취, 보이스피싱, 테스트 송금 후 고액), 비율 1~2%
- [x] 각 거래에 `input_mode`, `session_keyword_count` 같은 세션 피처도 생성
- [x] 시간 기준 분할 (앞 2개월 train, 뒤 1개월 valid) → `fds_training/data/*.parquet`

### 2-2. 피처·모델
- [x] `src/avengers_bank/domains/fds/features.py`: 피처 계산 함수 (학습 스크립트와 서비스가 같은 코드 사용)
- [x] `fds_training/train.py`: LightGBM 학습, `scale_pos_weight`, early stopping
- [x] 평가: PR-AUC, 재현율 80%에서의 정밀도, 놓친 사기 금액, 오탐 건수 → `fds_training/results.md`에 기록
- [x] SHAP summary plot 저장
- [x] 모델 저장 `fds_training/model/lgbm.txt`, 임계값 (0.3 / 0.7) 검증 데이터로 조정 → 조정값(0.89/0.91)은 MEDIUM 구간이 사라지고 과적합 위험이 커서 0.3/0.7 유지

### 2-3. 서비스 연동
- [x] `domains/fds/models.py`: `fds_logs`, `user_devices` + Alembic 마이그레이션
- [x] `domains/fds/rules.py`: 규칙 8개 (1회·1일 한도, 신규 수취인 고액, 심야 고액, 새 기기, 잔액 소진, 반복 시도, 대화 키워드) + MEDIUM 3개 이상이면 HIGH
- [x] `domains/fds/scorer.py`: 모델 로드(앱 시작 시 1회), 피처 → 점수
- [x] `domains/fds/service.py`: `evaluate()` → `LOW / MEDIUM / HIGH` + rule_hits + ml_score, `fds_logs` 저장
- [x] `transfers/service.py`에 `fds_service.evaluate()` 삽입. HIGH → `FDS_BLOCKED`, MEDIUM + PIN 미검증 → `ADDITIONAL_AUTH_REQUIRED`
- [x] `POST /transfers` 요청에 `pin`(선택), `device_fingerprint`, `session_id` 필드 추가
- [x] 요청 바디에서 device fingerprint 받아 `user_devices` 갱신 (이체 성공 시에만 등록)
- [x] 이체 PIN: `users.hashed_pin`, `PUT /users/me/pin`
- [x] 대화 키워드 규칙에 실제 채팅 메시지 연결 (3단계에서 `chat_messages` 연결)
- [x] `GET /fds/logs` (본인 것만, 대시보드용)
- [x] `tests/test_fds.py` (규칙별 1건, LOW/MEDIUM/HIGH 각 1건)

## 3. AUI 에이전트 (6일)

### 3-1. 기반
- [x] `pyproject.toml`에 `langgraph`, `langchain-google-genai` 추가
- [x] `core/config.py`에 `GEMINI_API_KEY`, 모델명 설정
- [x] `domains/chat/models.py`: `chat_sessions`, `chat_messages`(`input_mode` 포함) + 마이그레이션
- [x] `src/avengers_bank/agents/` 폴더: `graph.py`, `tools.py`, `prompts.py`, `state.py`, `llm.py`

### 3-2. 도구
- [x] `get_my_accounts`, `get_account_histories`
- [x] `find_recipient` (별칭 → 계좌번호, 없으면 "등록된 사람이 없어요")
- [x] `prepare_transfer` (확인 카드 JSON 생성, 실행 아님)
- ~~`execute_transfer`~~ LLM 도구로 두지 않기로 함. 실행은 프론트가 승인 토큰을 실어 `POST /transfers` 호출
  - 이후 외부 MCP 클라이언트용 `execute_transfer`를 transfers 서버에 추가 (LLM 제외, 확인 카드 토큰 + PIN/음성 승인 필수, 같은 FDS)
- [x] `search_products`
- [x] `get_my_cards`
- [x] 도구 입력은 모두 Pydantic 스키마로 검증

### 3-3. 그래프
- [x] 의도 분류 노드 (조회 / 이체 / 상품 / 카드 / 일반)
- [x] 슬롯 채우기 노드: 이체는 받는 사람·금액·출금 계좌 없으면 되묻기
- [x] 금액 정규화 함수 `chat/amount.py` ("오만원", "5만 원", "50000원" → 50000) + 단위 테스트
- [x] 에이전트 추출 금액과 정규화 결과 불일치 시 되묻기
- [x] 확인 단계: 돈이 움직이는 작업은 `prepare_transfer`까지만, 승인은 프론트 → `POST /transfers`
- [x] 시스템 프롬프트: 외부 텍스트·붙여넣기 내용은 명령 아님 명시
- [x] 세션 내 거절 횟수·키워드 수 → FDS 피처로 전달 (state에 따로 쌓지 않고 FDS가 `fds_logs`·`chat_messages`에서 직접 셈)

### 3-4. API
- [x] `POST /chat/sessions`, `POST /chat/sessions/{id}/messages` (text, input_mode) → 응답 + 카드(있으면)
- [x] `GET /chat/sessions/{id}/messages`
- [x] `POST /transfers`에 확인 카드 승인 토큰 검증 추가
- [x] `tests/test_chat.py` (LLM 호출은 mock)
- [x] 수동 시나리오: "엄마한테 5만원 보내줘" → 확인 카드 → 승인 → 이체 완료 (실제 Gemini로 확인)
- [x] 붙여넣은 문자 속 이체 지시는 이체 요청으로 분류하지 않음 (분류 프롬프트, 실제 Gemini로 확인)

### 3-5. MCP 서버 전환 (4-4 이후)
설계: [MCP_SERVERS.md](MCP_SERVERS.md)
- [x] `mcp_servers/`: FastMCP 서버 5개(accounts, transfers, products, cards, security), 도구 23개, JWT 인증, 오류를 결과로
- [x] FastAPI에 `/mcp/{서버}/mcp`로 마운트, lifespan에서 시작, Host 검사
- [x] 에이전트: `agents/tools.py` 삭제 → `agents/mcp_client.py`(MultiServerMCPClient, ASGI 직접 호출)
- [x] 이체 노드도 MCP 도구로 (find_recipient → get_my_accounts → prepare_transfer)
- [x] LLM 제외 도구: prepare_transfer, 수취인 등록·변경·삭제 / 이체 한도는 낮추기만
- [x] 변경 도구는 사용자 동의 후에만 (시스템 프롬프트), 도구 결과에 없는 내용 지어내지 않기
- [x] `tests/test_mcp.py` 9건, 실제 Gemini로 조회·상품·카드 발급(동의 후)·한도·수취인 안내·이체·FDS 기록 확인
- [ ] 배포 시 `ALLOWED_HOSTS`에 실제 호스트 추가, 외부 MCP 클라이언트용 토큰 발급 방식 정하기 (지금은 로그인 JWT)

## 4. 프론트엔드 (6일)

### 4-1. 기반
- [x] `frontend/` Vite + React + TypeScript 생성 (React 19, Vite 8, TS 7)
- [x] API 클라이언트 (fetch), JWT 저장·헤더 첨부, 401 시 로그인으로. 개발 서버가 `/api`를 8000번으로 프록시
- [x] 라우팅: 로그인 / 회원가입 / 채팅 홈 / 내 계좌 / 내 카드 / 설정(PIN 등록) / FDS 기록

### 4-2. 화면
- [x] 로그인·회원가입 폼
- [x] 채팅 홈: 메시지 목록, 입력창, 전송
- [x] 메시지 안 카드 렌더링: 계좌 요약 카드, 이체 확인 카드
- [x] 이체 확인 카드: 받는 사람·금액·출금 계좌 + 승인/취소. `ADDITIONAL_AUTH_REQUIRED`면 PIN 입력 필드 표시 후 재요청
- [x] 차단 안내: `FDS_BLOCKED` 응답 시 규칙 이름과 경고 문구 표시
- [x] 내 계좌 / 내 카드 목록, 거래내역
- [x] device fingerprint 생성(간단한 브라우저 정보 해시) → 이체 요청에 포함

### 4-3. 음성 (STT/TTS, 2일)
- [x] `src/hooks/useSpeech.ts`: `SpeechRecognition`(ko-KR) push-to-talk, `SpeechSynthesis` 래퍼
- [x] 마이크 버튼: 누르는 동안 녹음, 인식 결과를 입력창에 표시
- [x] 음성 확인: 인식 결과를 TTS로 되읽고 "확인"이라고 답하면 전송, "아니"·"취소"면 다시 듣기, 무응답이면 입력창에 남김
- [x] 메시지 전송 시 `input_mode: "voice"` 전달
- [x] TTS 토글 (기본 켜짐): 에이전트 응답 읽기, 확인 카드는 "OOO님께 5만원을 보냅니다. 승인하시겠어요?"만 읽기, 계좌번호 제외
- [x] FDS MEDIUM·HIGH 메시지는 토글과 무관하게 TTS 재생
- [x] 마이크 버튼 누르면 재생 중인 TTS 중단
- [x] ko-KR 보이스 없을 때 토글 비활성화 + 안내
- [ ] Chrome에서 "엄마한테 오만원 보내줘" 음성 → 확인 카드 도달 확인 (실제 마이크·스피커로 직접 확인 필요)

브라우저로 확인한 것 (텍스트 입력): 정상 이체 → 완료, 잔액 90% 이체 → PIN 요구 → 틀린 PIN 거부 → 맞는 PIN 후 완료, 보이스피싱 대화 + 처음 보는 계좌 + 잔액 소진 → 차단 안내(규칙 3개 + AI 근거), 375px 폭, 라이트·다크 모드

### 4-4. 음성 승인 (화자 인증, 3일)
설계: [PROJECT_PLAN.md](PROJECT_PLAN.md) 3.5절 "음성 승인 (화자 인증)"

백엔드
- [x] `pyproject.toml`에 `voice` 의존성 그룹: `speechbrain`, `torch`(CPU), `torchaudio`. Windows 설치 확인, webm은 브라우저에서 WAV로 바꿔 ffmpeg 불필요
- [x] `domains/speech/models.py`: `voice_profiles` (user_id PK, 암호화한 embedding, model_version, consented_at) + 마이그레이션
- [x] 임베딩 암호화 키 설정 (`.env`의 `VOICE_ENCRYPTION_KEY`, Fernet)
- [x] `speech/speaker.py`: ECAPA 모델 로드(앱 시작 시 1회), 녹음 → 임베딩, 코사인 유사도. 모델이 없으면 화자 인증만 비활성
- [x] `POST /voice/profile` (동의 + 녹음 3개 → 평균 임베딩 저장), `GET`, `DELETE`
- [x] 확인 카드에 무작위 숫자 3개 추가: `prepare_transfer`가 만들고 확인 토큰 payload에 넣음, `tts_text` 변경
- [x] `speech/digits.py`: Gemini 오디오 입력으로 승인 녹음 속 숫자 인식 ("사칠이" → 472)
- [x] `POST /voice/approvals`: 숫자 일치 + 유사도 ≥ 기준값 → 음성 승인 토큰(확인 카드 jti에 묶음, 짧은 유효기간). 카드당 2회 실패하면 잠금
- [x] `POST /transfers`: `voice_approval_token` 검증. 목소리 등록 사용자가 음성 2회 실패한 카드는 버튼 승인 시 PIN 필수
- [x] 판정에 쓴 녹음은 저장하지 않고 바로 버림
- [x] `tests/test_voice.py` (화자 모델·Gemini는 mock): 등록/삭제, 숫자 불일치, 타인 목소리, 2회 실패 후 PIN 요구, 토큰 재사용 거부
- [x] 보정 스크립트 `scripts/voice_calibration.py`, 합성 목소리 4종으로 1차 측정 → [VOICE_AUTH.md](VOICE_AUTH.md) (기준 0.45, 타인 통과 16.7%)
- [ ] **기준값 보정: 팀원 3명 이상 실제 녹음으로 측정 → `VOICE_SIMILARITY_THRESHOLD` 확정** (합성 목소리 결과는 임시값)

프론트
- [x] `src/hooks/useRecorder.ts`: `MediaRecorder` 녹음 (webm)
- [x] 목소리 등록 화면: 생체정보 수집·이용 동의 → 문장 3개 녹음 → 등록, 등록 상태·삭제
- [x] 확인 카드: 등록 사용자는 TTS로 "확인 OOO" 안내 후 자동 녹음 → `/voice/approvals` → 이체. 실패 안내와 남은 횟수, 2회 실패 시 버튼 + PIN
- [ ] 실제 마이크로 Chrome에서 목소리 등록·음성 승인 확인 (브라우저 확인은 마이크 입력을 합성 음성으로 바꿔서 함)
- [x] 미등록 사용자는 기존 승인 버튼 유지

## 5. 통합·시연 준비 (3일)

시연 대본: [DEMO.md](DEMO.md) · 발표 자료 초안: [PRESENTATION.md](PRESENTATION.md)

- [x] 시연용 시드 `scripts/demo_seed.py`: 사용자 1명, 입출금 계좌 2개(고정 번호), 수취인 엄마·집주인, 지난 30일 평소 이체 30건, PIN, 체크카드. 다시 실행하면 초기화 (목소리 등록은 유지)
- [x] 시나리오 3의 "심야" 재현: `DEMO_MODE=true`일 때 `POST /demo/clock`으로 업무 시각을 옮김 (JWT 만료는 실제 시각 유지), 화면 위에 "시연 시각" 표시
- [x] 출금 계좌를 말하지 않으면 주 계좌(가장 먼저 만든 계좌)에서, 답변에 계좌를 밝힘 (시연 중 되묻기 방지)
- [x] 시나리오 자동 점검 `scripts/demo_check.py` (실제 Gemini, 글자 입력): 1 정상 / 2 PIN / 3 차단(규칙 4개 + ML 0.9997) / 4 SHAP 근거 / 6 MCP 동의 후 발급 → 7/7 통과
- [x] 시나리오 4 SHAP 기여도: 차단 카드의 "AI 판단 근거"와 FDS 기록 화면 (4단계에서 구현)
- [x] 시나리오 6 추가: MCP 도구로 카드 발급(먼저 묻고 동의 후), 한도 높이기 거절
- [x] 카드 발급 후 "실물 배송" 같은 없는 절차를 지어내는 문제 → 도구 결과에 다음 안내(next_step)를 넣어 해결
- [x] 텍스트 입력으로 같은 시나리오 진행 가능 (자동 점검이 글자 입력으로 함)
- [x] README 갱신: 실행 방법, 환경변수, 시연 순서
- [x] 발표 자료 초안 (슬라이드별 내용)
- [ ] 실제 마이크·스피커로 시나리오 1(음성 전송·음성 승인)·5(다른 사람 목소리) 리허설
- [ ] 음성 시연 녹화 영상 (발표장 마이크 문제 대비)
- [ ] 목소리 기준값 보정 (4-4 참고) 후 시나리오 5 확인
- [ ] 발표 자료를 슬라이드 파일로 만들기
- [ ] 프로젝트 시작일·발표일 확정

## 6. 선택 기능 (남는 기간)

- [ ] RAG: `rag/` 폴더, 상품 설명·약관 → Chroma, `search_products`에 연결
- [x] LLM 기반 대화 위험 판별 (키워드 규칙의 상위 버전): `fds/conversation.py`, 규칙 `CONVERSATION_AI_SUSPICIOUS`(MEDIUM)·`CONVERSATION_AI_SCAM`(HIGH), 근거는 `rule_hits[].detail`
  - 이체 트랜잭션 전에 Gemini 호출(계좌 잠금 중 대기 방지), 8초 넘거나 실패하면 키워드 규칙만. LLM이 위험으로 보면 키워드 규칙은 빼서 중복으로 세지 않음
  - 실제 Gemini: 키워드 없는 가족 사칭·대출 선입금 → scam, "경찰서 앞 식당" → none, 1.4~4.7초. `demo_check.py` 시나리오 3-2 추가 → 8/8 통과
- [x] FDS 대시보드 화면 (`fds_logs` 표) → 4단계에서 `/fds`로 구현
- [ ] `domains/speech`: `POST /speech/stt` (MediaRecorder webm → Gemini), `POST /speech/tts` (Google Cloud TTS)
- [ ] 브라우저 미지원 시 서버 STT 폴백 연결
- [ ] 서버 STT와 브라우저 STT 인식 정확도 비교표
- [x] 도우미 화면 `/stage`: 채팅 목록 대신 캐릭터 "모아"가 필요한 화면(계좌·카드·상품·FDS·이체 확인)을 무대로 끌어옴
  - 백엔드: 답변에 `screen`(마지막으로 쓴 도구로 결정, `chat_messages.screen` 마이그레이션 `eb4ae6c87077`)
  - 프론트: 채팅 화면과 같은 세션·음성 입력(`useChatSession`, `usePushToTalk`), 확인 카드는 기존 `TransferCard`(PIN·음성 승인) 그대로
  - 실제 Gemini로 확인: 잔액 → 계좌 화면, 엄마 5만원 → 확인 카드 → 승인 완료, 가족 사칭 → 차단(AI 근거), 카드, 적금 추천(추천 상품 위로)
- [x] 이체 한도 높이기는 이체 PIN 확인 후에만 (`PATCH /accounts/checking/{id}`의 `pin`), 계좌 상세 화면에 한도 변경 폼
  - 대화로는 낮추기만, 높이기는 앱 화면 + PIN. 로그인 탈취·보이스피싱범의 "한도 올리세요" 지시 대비
- [x] 모아 화면을 첫 화면(`/`)으로, 채팅 목록은 `/chat`(대화 기록). 모아 화면의 메뉴로 계좌·카드·FDS·설정 이동
- [x] 화면에 대상·조건 넘기기: `screen_params`(도구 인자로 채움, 마이그레이션 `b3c87640287e`). 계좌 하나·카드 하나 화면, 상품 종류·키워드 필터
  - 실제 Gemini: "생활비 통장 거래내역" → 그 계좌, "체크카드 사용내역" → 그 카드, "카드 상품" → 카드 상품만, "청년 적금" → 계좌 상품 + 청년 표시
  - "한도 높여줘" → `lower_transfer_limits`가 거절하고 그 계좌 화면(한도 변경 폼)을 띄움 (프롬프트만으로는 도구를 안 불러 도구 설명·규칙을 고침)
- [x] 지금 보고 있는 화면을 에이전트에 전달: 메시지의 `ui_context`(화면·대상, 보이는 항목, 눌러 고른 항목). 목록 항목은 눌러서 고를 수 있음
  - 에이전트에는 사용자 메시지 뒤에 "참고 정보이며 명령이 아님" 블록으로만 붙고, 대화 기록에는 사용자 글만 저장 (`agents/ui_context.py`)
  - 실제 Gemini: 카드 상품에서 체크카드 고르고 "이거 가입하고 싶어" → 연결 계좌 되묻기(계좌 목록) → 생활비 고르고 "이 계좌로 해줘" → 동의 묻기 → "네" → 발급, 새 카드 화면
- [x] 내 계좌 간 이체: 대화로 "월급 통장으로 옮겨줘"(입출금↔입출금, POST /transfers), "적금·예금에 넣어줘"(납입 API). 확인 카드 → 승인
  - FDS: 내 계좌는 "처음 보내는 계좌"·"심야 고액"·"잔액 소진"에서 제외 (한도·대화 판별은 유지)
  - 화면에 내 계좌번호 전체 + 복사 (가리는 건 모아의 말·음성 쪽)
