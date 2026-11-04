# AvengersBank 프로젝트 계획서

- 작성일: 2026-11-04
- 인원: 1명 (개인 프로젝트)
- 기간: 미정 (아래 "일정"의 단계별 소요 일수를 기준으로 시작일·발표일이 정해지면 날짜를 채운다)
- 관련 문서: [ERD.md](ERD.md) · [API_ENDPOINTS.md](API_ENDPOINTS.md) · [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)

---

## 1. 프로젝트 개요

### 1.1 한 줄 소개

**일반 사용자가 말이나 글로 은행 업무(조회·이체·상품 가입·카드)를 처리할 수 있는 AI 에이전트 기반 뱅킹 앱**, 그리고 그 에이전트가 실행하는 거래를 실시간으로 검사하는 **이상거래 탐지 시스템(FDS)**.

### 1.2 배경과 문제 정의

- 기존 모바일 뱅킹은 메뉴 깊이가 깊어서 고령층·디지털 취약계층이 쓰기 어렵다. "엄마한테 5만원 보내줘"처럼 말로 끝나는 **AUI(Agentic User Interface)**가 해결책이 될 수 있다. 특히 고령층은 타이핑보다 음성이 편하므로 **음성 입력(STT)과 음성 안내(TTS)**를 기본 인터페이스로 둔다.
- 하지만 AUI는 새로운 위험을 만든다. 에이전트가 대신 실행하므로 사용자가 보이스피싱에 속아 명령하거나, 계정이 탈취되면 **정상 인증을 통과한 사기 거래**가 발생한다.
- 따라서 이 프로젝트는 "편리한 AUI"와 "그 AUI를 안전하게 만드는 FDS"를 한 세트로 구현한다.

### 1.3 목표

| 구분 | 목표 |
|---|---|
| 필수 | 은행 백엔드 API 완성 (회원·상품·계좌·이체·카드) |
| 필수 | LangGraph 에이전트가 자연어 요청을 API 호출로 바꿔 실행 (조회·이체·상품 상담) |
| 필수 | 이체 시 규칙 엔진 + LightGBM 위험 점수로 통과 / 추가 인증 / 차단 판정 |
| 필수 | React 기반 채팅형 프론트엔드 (로그인, 대화, 거래 확인 화면) |
| 필수 | 음성 입력(STT)으로 말한 내용을 에이전트에 전달하고, 에이전트 응답을 음성(TTS)으로 읽어 줌 |
| 선택 | 상품 설명·약관 RAG 상담 (Chroma) |
| 선택 | 에이전트 대화에서 보이스피싱 정황을 잡는 LLM 기반 대화 위험 판별 |
| 선택 | 서버 측 STT(Gemini 오디오 입력)로 브라우저 미지원 환경 보완, 음성 인식 정확도 비교 |

### 1.4 범위에서 제외하는 것

- 실제 금융기관 연동, 실명 인증, 공인 인증서
- 대출 도메인 (초안 ERD의 `loans`, `loan_schedules`)은 이번 범위에서 제외
- 푸시 알림, 자동이체 스케줄러

---

## 2. 시스템 구성

### 2.1 전체 아키텍처

```
┌──────────────────────┐
│  Frontend (React)    │  채팅 UI, 계좌·카드 화면, 이체 확인·추가 인증 화면
│  + Web Speech API    │  STT(마이크 → 텍스트), TTS(응답 텍스트 → 음성)
└──────────┬───────────┘
           │ REST (JWT)
┌──────────▼───────────┐
│  FastAPI Backend     │
│  ├ domains/users     │  회원가입·로그인
│  ├ domains/products  │  계좌·카드 상품 카탈로그
│  ├ domains/accounts  │  입출금·예금·적금 계좌, 거래내역
│  ├ domains/transfers │  이체·납입  ──▶  FDS 검사 후 실행
│  ├ domains/cards     │  신용·체크카드, 결제
│  ├ domains/chat      │  대화 API ──▶ LangGraph 에이전트
│  ├ domains/speech    │  (선택) 오디오 업로드 → Gemini STT, 텍스트 → TTS 파일
│  └ domains/fds       │  규칙 엔진 + LightGBM 스코어링
└──────────┬───────────┘
           │
┌──────────▼───────────┐   ┌──────────────┐   ┌─────────────┐
│  PostgreSQL          │   │ Gemini API   │   │ Chroma (RAG)│
└──────────────────────┘   └──────────────┘   └─────────────┘
```

### 2.2 기술 스택

| 영역 | 기술 | 비고 |
|---|---|---|
| 백엔드 | Python 3.13, FastAPI, SQLAlchemy(async), Alembic, PostgreSQL | 현재 뼈대 그대로 |
| 인증 | JWT (pyjwt), Argon2 (pwdlib) | 구현 완료 |
| 에이전트 | LangGraph, Gemini API (langchain-google-genai) | 의도 분류 → 도구 호출 → 응답 |
| RAG (선택) | Chroma, Gemini 임베딩 | 상품 설명·약관 |
| FDS | 규칙 엔진 (순수 Python), LightGBM, pandas, scikit-learn | 합성 데이터로 학습 |
| 프론트엔드 | React (Vite), TypeScript | CORS가 이미 `localhost:5173`으로 열려 있음 |
| STT | 브라우저 Web Speech API `SpeechRecognition` (`lang: ko-KR`) | 무료, 서버 불필요. Chrome·Edge 지원 |
| TTS | 브라우저 Web Speech API `SpeechSynthesis` (ko-KR 보이스) | 무료. 선택: Google Cloud TTS로 음질 개선 |
| 서버 STT (선택) | Gemini API 오디오 입력 (webm/ogg 업로드) | 브라우저 미지원 시 폴백, 인식 정확도 비교용 |
| 테스트 | pytest, httpx, aiosqlite | PostgreSQL 없이 실행 가능 |

### 2.3 데이터 모델

기준은 [ERD.md](ERD.md)의 13개 테이블이다. 여기에 이번 프로젝트에서 다음 테이블을 추가한다.

| 추가 테이블 | 용도 | 주요 컬럼 |
|---|---|---|
| `chat_sessions` | 대화 묶음 | session_id PK, user_id FK, created_at |
| `chat_messages` | 대화 내용 | msg_id PK, session_id FK, role(user/assistant/tool), content, intent, created_at |
| `recipients` | 자주 보내는 수취인 ("엄마", "집주인") | recipient_id PK, user_id FK, account_num, holder_name, nickname, last_sent_at |
| `fds_logs` | FDS 판정 기록 | fds_log_id PK, user_id FK, tx_type, amount, rule_hits(JSON), ml_score, risk_level, decision, created_at |
| `user_devices` | 기기·IP 이력 (FDS 피처용) | device_id PK, user_id FK, device_fingerprint, ip, first_seen, last_seen |

`chat_messages`에는 `input_mode` 컬럼(text/voice)을 둔다. 음성으로 들어온 이체 요청인지가 FDS 피처와 시연 통계에 쓰인다.

`recipients`는 에이전트가 "엄마한테 보내줘"를 계좌번호로 바꾸는 데 필요하고, 동시에 FDS의 "신규 수취인 여부" 피처의 근거가 된다.

---

## 3. 기능 상세

### 3.1 은행 백엔드 API

[API_ENDPOINTS.md](API_ENDPOINTS.md)의 📝 항목을 모두 ✅로 만드는 것이 목표다. 구현 순서는 의존 방향을 따른다.

1. `products` — 조회 전용. 시드 데이터(입출금 1종, 예금 2종, 적금 2종, 신용·체크카드 각 1종) 포함
2. `accounts` — 개설, 조회, 거래내역, 별칭·한도 변경. 계좌번호 발급은 세 테이블 중복 검사
3. `transfers` — 이체, 적금 납입, 예금 입금. **FDS 검사를 이 service 안에서 호출**
4. `cards` — 발급, 결제. 체크카드는 연결 계좌 즉시 출금
5. `users` PATCH, `recipients` CRUD

### 3.2 AUI (LangGraph 에이전트)

**흐름**

```
사용자 음성 ──(STT)──▶ 텍스트  또는  사용자 타이핑
  → [의도 분류] 조회 / 이체 / 상품 상담 / 카드 / 일반 대화
  → [슬롯 채우기] 이체라면 받는 사람·금액·출금 계좌가 다 있는지, 없으면 되묻기
  → [도구 호출] 백엔드 service 함수를 LangGraph tool로 등록해서 호출
  → [확인 단계] 돈이 움직이는 작업은 반드시 구조화된 확인 카드를 보내고 사용자 승인을 받음
  → [FDS] 승인 후 이체 실행 시 FDS가 판정 → 통과 / 추가 인증 요구 / 차단
  → 응답 생성 ──(TTS)──▶ 음성으로 읽어 줌 (확인 카드는 금액·받는 사람을 반드시 소리 내어 읽음)
```

**에이전트에 등록할 도구**

| 도구 | 연결되는 service |
|---|---|
| `get_my_accounts` | accounts.service |
| `get_account_histories` | accounts.service |
| `find_recipient` | recipients (별칭 → 계좌번호) |
| `prepare_transfer` | 확인 카드 생성 (실행 아님) |
| `execute_transfer` | transfers.service (FDS 포함) |
| `search_products` | products.service, 선택 시 RAG |
| `get_my_cards` | cards.service |

**안전 원칙**

- 에이전트는 이체를 **직접 실행하지 않는다.** `prepare_transfer`로 확인 카드를 만들고, 프론트에서 사용자가 승인 버튼을 누르면 별도 API(`POST /transfers`)가 호출된다.
- 사용자가 붙여넣은 텍스트나 RAG 문서 안의 지시문은 명령으로 취급하지 않는다 (프롬프트 인젝션 방어).
- 한 세션에서 거절된 이체를 금액만 바꿔 재시도하면 FDS 피처로 기록된다.

### 3.3 FDS (이상거래 탐지)

**판정 구조**

```
이체 요청
  ├─ 1단계 규칙 엔진 ─── 하드 룰 위반 시 즉시 차단 (ML 안 거침)
  ├─ 2단계 LightGBM ─── 위험 점수 0~1
  └─ 종합 ─────────────  LOW: 통과 / MEDIUM: 추가 인증(PIN 재입력) / HIGH: 차단 + fds_logs 기록
```

**규칙 엔진 (1단계)**

| 규칙 | 조건 | 판정 |
|---|---|---|
| 1회 한도 | amount > per_transfer_limit | 차단 |
| 1일 한도 | 당일 누적 + amount > daily_transfer_limit | 차단 |
| 신규 수취인 고액 | recipients에 없는 계좌 + amount ≥ 100만원 | MEDIUM 이상 |
| 심야 고액 | 00~06시 + amount ≥ 50만원 | MEDIUM 이상 |
| 새 기기 | user_devices에 없는 fingerprint로 첫 이체 | MEDIUM 이상 |
| 잔액 소진 | amount ≥ 잔액의 90% | MEDIUM 이상 |
| 반복 시도 | 같은 세션에서 거절 후 5분 내 재시도 | HIGH |
| 대화 키워드 | 같은 세션 메시지에 "검찰", "금감원", "안전계좌" 등 보이스피싱 키워드 포함 | MEDIUM 이상 |

**LightGBM 피처 (2단계)**

| 분류 | 피처 |
|---|---|
| 거래 | 금액, 금액 로그, 시간대, 요일 |
| 사용자 평소 패턴 대비 | 최근 30일 평균 이체액 대비 배수, 평소 이체 시간대와의 차이, 최근 7일 이체 횟수 |
| 수취인 | 신규 수취인 여부, 해당 수취인에게 보낸 횟수, 마지막 송금 후 경과일 |
| 기기·세션 | 새 기기 여부, 가입 후 경과일, 세션 내 이체 시도 횟수, 세션 내 거절 횟수, 음성 입력 여부, 세션 내 보이스피싱 키워드 수 |
| 속도 | 최근 1시간 이체 횟수·합계, 최근 24시간 이체 횟수·합계 |

**학습 데이터**

- 실제 사기 데이터가 없으므로 **합성 데이터 생성기**를 만든다. 정상 사용자 500명의 3개월치 거래를 평소 패턴(급여일, 월세, 소액 결제)대로 만들고, 그중 1~2%에 사기 시나리오를 섞는다.
- 사기 시나리오: 계정 탈취(새 기기 + 신규 수취인 + 잔액 소진), 보이스피싱(심야 + 고액 + 평소의 10배), 테스트 송금 후 고액(소액 1건 직후 고액 1건).
- 분할은 시간 기준(앞 2개월 학습, 뒤 1개월 검증).

**평가 지표**

- PR-AUC (주 지표), 재현율 80%에서의 정밀도
- 비즈니스 지표: 놓친 사기 금액, 정상 거래 오탐 건수
- SHAP로 피처 기여도를 뽑아 "왜 막혔는지"를 에이전트 응답에 반영

### 3.4 프론트엔드 (React)

| 화면 | 내용 |
|---|---|
| 로그인 / 회원가입 | JWT 저장 |
| 채팅 홈 | 에이전트와 대화. 메시지 안에 계좌 요약 카드, 이체 확인 카드가 렌더링 |
| 이체 확인 카드 | 받는 사람·금액·출금 계좌 표시 + 승인/취소 버튼. MEDIUM이면 PIN 입력 필드 추가 |
| 차단 안내 | HIGH 판정 시 사유(규칙 이름)와 "금융기관은 송금을 요구하지 않습니다" 경고 |
| 내 계좌 / 내 카드 | 목록과 거래내역 (채팅 없이도 확인 가능) |
| FDS 대시보드 (선택) | fds_logs를 표로 보여주는 관리자 화면. 발표용 |

채팅 홈에는 **마이크 버튼**과 **음성 안내 켜기/끄기 토글**이 있다. 세부는 3.5절.

### 3.5 음성 인터페이스 (STT / TTS)

**STT (음성 → 텍스트)**

| 항목 | 내용 |
|---|---|
| 방식 | 프론트에서 `SpeechRecognition`(ko-KR) 사용. 마이크 버튼을 누르고 있는 동안 녹음(push-to-talk) |
| 처리 | 인식 결과를 입력창에 보여주고 TTS로 "OOO라고 말씀하셨나요? 맞으면 '확인'이라고 말씀해 주세요"라고 묻는다. 사용자가 "확인"이라고 답하면 전송, "아니"·"취소"면 버리고 다시 듣는다. 대답이 없으면 입력창에 남겨 두고 전송 버튼으로 보낼 수 있다 |
| 숫자·금액 | "오만원", "5만 원", "50000원"을 모두 50000으로 바꾸는 정규화 함수를 백엔드 `chat.service`에 둔다. 에이전트가 추출한 금액과 정규식 결과가 다르면 되묻는다 |
| 폴백 | 브라우저가 `SpeechRecognition`을 지원하지 않으면 `MediaRecorder`로 녹음해 `POST /speech/stt`로 올리고 Gemini가 텍스트로 바꾼다 (선택 기능) |

**TTS (텍스트 → 음성)**

| 항목 | 내용 |
|---|---|
| 방식 | 프론트에서 `SpeechSynthesis`로 에이전트 응답을 읽는다. ko-KR 보이스가 없으면 토글을 비활성화하고 안내 |
| 읽는 범위 | 일반 응답은 전문. 확인 카드는 "OOO님께 5만원을 보냅니다. 승인하시겠어요?" 형태로 핵심만. 계좌번호는 읽지 않음 |
| FDS 연동 | MEDIUM·HIGH 판정 메시지는 TTS를 강제로 켠다. 보이스피싱 피해자는 화면을 안 읽고 상대 지시대로 누르는 경우가 많아, 경고를 귀로 듣게 하는 것이 목적 |
| 중단 | 사용자가 마이크 버튼을 누르면 재생 중인 TTS를 즉시 멈춘다 |

**음성 관련 API (선택, `domains/speech`)**

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/speech/stt` | 오디오 파일(webm) 업로드 → 텍스트. Gemini 오디오 입력 사용 |
| POST | `/speech/tts` | 텍스트 → mp3. Google Cloud TTS 사용. 브라우저 TTS 음질이 부족할 때만 |

**FDS와의 접점**

- `input_mode = voice`인 이체 요청은 FDS 피처에 포함한다. 단독으로 위험 신호는 아니지만 "음성 + 신규 수취인 + 고액" 조합은 보이스피싱 시나리오와 겹친다.
- STT 결과에 "검찰", "금감원", "안전계좌", "시키는 대로" 같은 키워드가 있으면 규칙 엔진의 **대화 키워드 규칙**(MEDIUM)으로 잡는다. 이는 선택 기능인 LLM 대화 위험 판별의 가벼운 버전이다.

---

## 4. 일정

1인 개발 기준이며, 단계별 소요 일수만 적는다. 시작일이 정해지면 날짜를 채운다. 총 **약 6주**로 예상한다.

| 단계 | 소요 | 산출물 | 완료 기준 |
|---|---|---|---|
| 0. 계획·환경 | 1일 | 이 문서, PostgreSQL·uv 환경, Alembic 초기 마이그레이션 | `uv run pytest` 통과, `/docs` 접속 |
| 1. 백엔드 API | 5일 | products → accounts → transfers → cards → recipients | API_ENDPOINTS.md 전부 ✅, 도메인별 테스트 |
| 2. 합성 데이터 + FDS | 5일 | 데이터 생성기, 규칙 엔진, LightGBM 학습 노트북, `domains/fds` | transfers.service에서 FDS 호출, PR-AUC 기록 |
| 3. AUI 에이전트 | 6일 | LangGraph 그래프, 도구 7개, `domains/chat` API | "엄마한테 5만원 보내줘" → 확인 카드 → 승인 → 이체 완료 시나리오 동작 |
| 4. 프론트엔드 | 6일 | React 앱 (로그인, 채팅, 확인 카드, 계좌·카드 화면) | 위 시나리오를 화면에서 끝까지 수행 |
| 4-1. 음성 (STT/TTS) | 2일 | 마이크 버튼, Web Speech API 연동, 금액 정규화, TTS 토글 | "엄마한테 오만원 보내줘"를 말로 해서 확인 카드까지 도달, 응답이 음성으로 재생 |
| 5. 통합·시연 준비 | 3일 | 사기 시나리오 3종 데모, SHAP 설명, 발표 자료 | 정상 이체 통과 / 보이스피싱 시나리오 차단 시연 |
| 6. 선택 기능 | 남는 기간 | RAG 상품 상담, 대화 위험 판별, FDS 대시보드, 서버 STT/TTS (`domains/speech`) | |

**우선순위 원칙:** 기간이 짧아지면 6 → 4의 계좌·카드 화면 → 3의 상품 상담 순으로 뺀다. 백엔드 API, FDS, 이체 대화 시나리오, 브라우저 STT/TTS는 끝까지 유지한다. (브라우저 음성은 서버 코드가 없어 비용이 작다.)

---

## 5. 폴더 구조 변경 계획

현재 구조([PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md))에 다음을 추가한다.

```
avengers_bank/
├── src/avengers_bank/
│   ├── domains/
│   │   ├── recipients/        # 수취인 (5개 파일 구조 동일)
│   │   ├── chat/              # 대화 API (models, schemas, router, service), 금액 정규화
│   │   ├── speech/            # (선택) STT/TTS API
│   │   └── fds/               # models(fds_logs, user_devices), rules.py, features.py, scorer.py, service.py
│   └── agents/                # LangGraph 그래프, tools.py, prompts.py
├── fds_training/              # 합성 데이터 생성기, 학습 노트북, 모델 파일(.txt), 평가 결과
├── data/seed/                 # 상품 시드 데이터 (JSON)
└── frontend/                  # React (Vite) 앱
    └── src/hooks/useSpeech.ts # SpeechRecognition / SpeechSynthesis 래퍼
```

`transfers.service.transfer()` 안의 순서는 다음과 같이 바뀐다.

```
async with db.begin():
    1. 본인 계좌 확인
    2. 받는 계좌 찾기
    3. 잔액·한도 검사
    4. fds_service.evaluate(...)  → LOW / MEDIUM / HIGH
       - HIGH: BadRequestException("FDS_BLOCKED") + fds_logs 기록
       - MEDIUM: PIN 미검증이면 BadRequestException("ADDITIONAL_AUTH_REQUIRED")
    5. 양쪽 balance 변경
    6. 양쪽 History 저장
    7. fds_logs 기록
```

---

## 6. 리스크와 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| 1인 개발로 범위가 넓음 | 일정 지연 | 4절의 우선순위 원칙대로 선택 기능부터 제외 |
| 실제 사기 데이터 없음 | 모델 신뢰도 낮음 | 합성 시나리오를 문서화하고, 규칙 엔진이 1차 방어를 맡아 모델 실패에도 최소 안전 확보 |
| Gemini API 응답 지연·비용 | 데모 품질 | 의도 분류는 작은 모델(flash 계열), 도구 호출 결과는 캐시. 요청 수 로그로 비용 추적 |
| 에이전트가 잘못된 금액·수취인 추출 | 오송금 | 확인 카드 승인 없이는 절대 실행 안 함. 금액은 정규식으로 2차 검증 |
| 프롬프트 인젝션 | 보안 사고 시연에서 역효과 | 시스템 프롬프트에 외부 텍스트 비신뢰 명시, 도구 입력은 Pydantic 스키마로 검증 |
| PostgreSQL 환경 문제 | 개발 중단 | 테스트는 SQLite로 동작하도록 이미 구성됨. 데모도 SQLite 폴백 가능하게 유지 |
| 한국어 STT 오인식 (금액·이름) | 오송금 | 인식 결과를 입력창에 먼저 표시해 수정 기회 제공, 금액 정규화 + 확인 카드에서 TTS로 금액을 다시 읽어 줌 |
| Web Speech API 브라우저 제한 | 데모 환경에서 동작 안 함 | 시연은 Chrome으로 고정. 선택 기능인 서버 STT를 폴백으로 준비 |
| 발표장 소음·마이크 문제 | 시연 실패 | 음성 시연은 녹화 영상도 준비하고, 텍스트 입력으로 같은 시나리오를 바로 이어갈 수 있게 함 |

---

## 7. 시연 시나리오 (발표용)

1. **정상 이체(음성):** 마이크 버튼을 누르고 "엄마한테 오만원 보내줘" → STT 결과 표시 → 확인 카드 + TTS로 "엄마님께 5만원을 보냅니다" 읽음 → 승인 → LOW 통과 → 잔액 반영 화면
2. **추가 인증:** 처음 보는 계좌로 150만원 → 신규 수취인 고액 규칙 → MEDIUM → PIN 입력 후 완료
3. **차단:** 새벽 2시, 잔액의 95%, 신규 수취인, 대화에 "검찰에서 안전계좌로 옮기라고" 포함 → 규칙 3개 + ML 점수 0.9 → HIGH 차단, 보이스피싱 경고를 TTS로 강제 재생, fds_logs에 기록
4. **설명:** SHAP 기여도로 "새 기기, 평소 대비 12배 금액"이 핵심 원인이었음을 표시

---

## 8. 팀에서 정해야 할 것 (ERD.md 미결 항목 포함)

**1단계 구현에서 확정한 것** (코드에 반영됨)

- 거래내역 `type` 값: `DEPOSIT`, `WITHDRAW`, `TRANSFER_IN`, `TRANSFER_OUT`, `CARD_PAYMENT`, `SAVINGS_PAYMENT`, `DEPOSIT_PAYMENT`, `INTEREST` (`accounts/models.py`의 `HistoryType`). `DEPOSIT_PAYMENT`(입출금 → 예금 입금)는 구현 중 추가
- 계좌번호 형식: `110-XXX-XXXXXX` (입출금), `220-…` (예금), `330-…` (적금)
- 카드번호 형식: `9410-XXXX-XXXX-XXXX` (신용), `9420-…` (체크)
- 이체 한도 기본값: 1회 500만원, 1일 1,000만원. 1일 기준은 한국 시간 0시
- 이체 성공 시 수취인 자동 등록: 하지 않음 (등록된 수취인이면 `last_sent_at`만 갱신)

**2단계 구현에서 확정한 것**

- FDS 임계값: ML 점수 0.3 미만 LOW, 0.3~0.7 MEDIUM, 0.7 이상 HIGH 유지. 검증 데이터로 조정한 값은 MEDIUM 구간이 거의 없어져 쓰지 않음 ([fds_training/results.md](../fds_training/results.md))
- 규칙과 ML 종합: 둘 중 높은 등급. MEDIUM 규칙이 3개 이상 겹치면 ML과 무관하게 HIGH
- 추가 인증: 숫자 6자리 이체 PIN (`PUT /users/me/pin`으로 등록, Argon2 해시 저장)
- 기기 등록: 로그인이 아니라 이체에 성공했을 때. 등록 기기가 하나도 없는 사용자의 첫 기기는 새 기기로 보지 않음
- 반복 시도: 같은 세션에서 차단(BLOCKED)된 뒤 5분 안에 다시 이체하면 HIGH

**3단계 구현에서 확정한 것**

- Gemini 모델 분리: 의도 분류·슬롯 추출은 `gemini-2.5-flash`(약 1.5초), 조회·상담 답변은 `gemini-3.8-flash`. `.env`의 `GEMINI_FAST_MODEL`, `GEMINI_CHAT_MODEL`로 변경
- 이체 흐름은 LLM의 자유 도구 호출이 아니라 코드로 처리: LLM은 의도·슬롯만 뽑고, 금액 재검증·수취인 조회·확인 카드 생성은 `agents/graph.py`의 정해진 순서
- 확인 카드 승인 토큰: 5분 유효, 세션당 최신 카드 1장만 유효, 이체 성공 시 소모. `POST /transfers`에 `session_id`가 있으면 토큰 필수

**4단계 시작 전 확정한 것**

- STT 전송 방식: 인식 결과를 TTS로 되읽어 확인을 묻고, 사용자가 "확인"이라고 답하면 전송 ("아니"·"취소"면 다시 듣기, 무응답이면 입력창에 남김)
- TTS 기본값: 켜짐 (FDS MEDIUM·HIGH 경고는 설정과 무관하게 항상 재생)

**아직 정해야 할 것**

- 프로젝트 시작일·발표일 → 4절의 날짜 확정
