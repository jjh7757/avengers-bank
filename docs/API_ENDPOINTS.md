# API 엔드포인트

- 실행 중인 서버에서는 `http://127.0.0.1:8000/docs`(Swagger)에서 직접 호출해 볼 수 있습니다.
- 🔒 표시가 있는 API는 `Authorization: Bearer <access_token>` 헤더가 필요합니다.
- 상태: ✅ 구현됨 / 📝 TODO

## 공통 응답 형식

성공:
```json
{ "data": { ... }, "message": "회원가입이 완료되었습니다." }
```

실패:
```json
{ "error": { "code": "INSUFFICIENT_BALANCE", "message": "잔액이 부족합니다.", "details": [] } }
```

| HTTP | 언제 | 예외 클래스 (`core/exceptions.py`) |
|---|---|---|
| 400 | 잔액 부족, 한도 초과 등 처리 불가 | `BadRequestException` |
| 401 | 로그인 안 함, 토큰 만료 | `UnauthorizedException` |
| 403 | 남의 계좌·카드에 접근 | `ForbiddenException` |
| 404 | 계좌·카드·상품 없음 | `NotFoundException` |
| 409 | 아이디·수취인 중복 | `ConflictException` |
| 422 | 입력값 형식 오류 (FastAPI 자동) | — |

`code`는 `ACCOUNT_NOT_FOUND`, `DAILY_LIMIT_EXCEEDED`처럼 **대문자 스네이크 케이스**로 구체적으로 적습니다.

---

## users: 회원 (`domains/users`)

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/users/signup` | | 회원가입 |
| ✅ | POST | `/users/login` | | 로그인, JWT 발급 |
| ✅ | GET | `/users/me` | 🔒 | 내 정보 조회 |
| ✅ | PATCH | `/users/me` | 🔒 | 이름, 닉네임, 전화번호 수정 |
| ✅ | PUT | `/users/me/pin` | 🔒 | 이체 PIN(숫자 6자리) 등록·변경. 비밀번호 재확인 `{ "password", "pin" }` |

<details>
<summary>요청·응답 예시</summary>

`POST /users/signup`
```json
{ "login_id": "ironman", "password": "password1234", "name": "토니 스타크", "nick_name": null, "phone": "010-1234-5678" }
```
→ `201`
```json
{ "data": { "user_id": 1, "login_id": "ironman", "name": "토니 스타크", "nick_name": null, "phone": "010-1234-5678", "created_at": "2026-11-04T10:00:00Z" }, "message": "회원가입이 완료되었습니다." }
```

`POST /users/login`
```json
{ "login_id": "ironman", "password": "password1234" }
```
→ `200`
```json
{ "data": { "access_token": "eyJhbGciOi...", "token_type": "bearer" }, "message": null }
```
</details>

## products: 상품 (`domains/products`)

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | GET | `/products/accounts?type=` | | 계좌 상품 목록 (`type` = CHECKING·DEPOSIT·SAVINGS, 생략하면 전체) |
| ✅ | GET | `/products/accounts/{product_id}` | | 계좌 상품 상세 |
| ✅ | GET | `/products/cards?type=` | | 카드 상품 목록 (`type` = CREDIT·DEBIT) |
| ✅ | GET | `/products/cards/{product_id}` | | 카드 상품 상세 |

## accounts: 계좌 (`domains/accounts`)

`{type}` = `checking` · `deposit` · `savings`

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | GET | `/accounts` | 🔒 | 내 계좌 전체 (3종 합쳐서) |
| ✅ | POST | `/accounts/checking` | 🔒 | 입출금 계좌 개설 |
| ✅ | POST | `/accounts/deposit` | 🔒 | 예금 계좌 개설 |
| ✅ | POST | `/accounts/savings` | 🔒 | 적금 계좌 개설 |
| ✅ | GET | `/accounts/{type}/{account_id}` | 🔒 | 계좌 상세 |
| ✅ | GET | `/accounts/{type}/{account_id}/histories` | 🔒 | 거래내역 |
| ✅ | PATCH | `/accounts/{type}/{account_id}` | 🔒 | 별칭, 이체 한도(입출금만) 변경 |

<details>
<summary>요청·응답 예시</summary>

`POST /accounts/checking` (한도 생략 시 1회 500만원, 1일 1,000만원)
```json
{ "product_id": 1, "nickname": "생활비", "per_transfer_limit": 5000000, "daily_transfer_limit": 10000000 }
```
`POST /accounts/deposit`
```json
{ "product_id": 2, "term_months": 12, "nickname": null }
```
`POST /accounts/savings`
```json
{ "product_id": 4, "term_months": 12, "monthly_payment": 300000, "monthly_deposit_date": 25 }
```
`PATCH /accounts/checking/1`: 보낸 필드만 변경. 이체 한도는 입출금 계좌만 (`400 TRANSFER_LIMIT_NOT_SUPPORTED`)
```json
{ "nickname": "월급통장", "per_transfer_limit": 1000000 }
```

`GET /accounts` → `200`
```json
{ "data": [
  { "account_type": "checking", "account_id": 1, "account_num": "110-123-456789", "balance": 500000, "nickname": "생활비", "created_at": "..." },
  { "account_type": "savings",  "account_id": 1, "account_num": "220-987-654321", "balance": 300000, "nickname": null, "created_at": "..." }
], "message": null }
```
`AccountSummaryResponse` 스키마는 `domains/accounts/schemas.py`에 정의되어 있습니다.
</details>

## transfers: 돈 이동 (`domains/transfers`)

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/transfers` | 🔒 | 입출금 → 입출금 이체 (잔액, 1회·1일 한도 검사) |
| ✅ | POST | `/transfers/savings` | 🔒 | 입출금 → 적금 납입 |
| ✅ | POST | `/transfers/deposit` | 🔒 | 입출금 → 예금 입금 |

<details>
<summary>요청·응답 예시</summary>

`POST /transfers`: `amount` 뒤의 필드는 선택입니다. 채팅에서 온 이체는 `session_id`와 확인 카드의 `confirmation_token`이 필요합니다.
```json
{ "from_checking_account_id": 1, "to_account_num": "110-555-000111", "amount": 10000,
  "pin": null, "device_fingerprint": "a1b2c3", "session_id": "9f2c...", "confirmation_token": "eyJ...", "input_mode": "voice" }
```
목소리를 등록한 사용자는 `voice_approval_token`(아래 voice 참고)을 넣거나, 없으면 `pin`이 필요합니다 (`400 PIN_REQUIRED`, `400 INVALID_VOICE_APPROVAL`).
확인 카드 관련 실패: `400 CONFIRMATION_REQUIRED`, `400 CONFIRMATION_MISMATCH`(카드와 금액·계좌가 다름), `400 CONFIRMATION_USED`(이미 썼거나 새 카드로 바뀜), `400 CONFIRMATION_EXPIRED`(5분), `404 CHAT_SESSION_NOT_FOUND`
→ `200`
```json
{ "data": { "from_account_num": "110-123-456789", "to_account_num": "110-555-000111", "to_holder_name": "브루스 배너", "amount": 10000, "balance_after": 490000, "transferred_at": "...", "risk_level": "LOW" }, "message": "이체가 완료되었습니다." }
```
실패: `400 INSUFFICIENT_BALANCE`, `400 PER_TRANSFER_LIMIT_EXCEEDED`, `400 DAILY_LIMIT_EXCEEDED`, `400 SAME_ACCOUNT`, `403 ACCOUNT_FORBIDDEN`, `404 ACCOUNT_NOT_FOUND`

**FDS 판정** (한도 검사를 통과한 뒤)

| 등급 | 응답 | 프론트가 할 일 |
|---|---|---|
| LOW | `200`, `risk_level: "LOW"` | |
| MEDIUM | `400 ADDITIONAL_AUTH_REQUIRED` | PIN 입력창을 띄우고 같은 요청에 `pin`을 넣어 다시 보냄. `extra.has_pin`이 false면 PIN 등록 안내 |
| MEDIUM + 틀린 PIN | `400 INVALID_PIN` | |
| HIGH | `400 FDS_BLOCKED` | `extra.rule_hits`의 이름과 `extra.warning`을 보여 주고 TTS로 읽음 |

```json
{ "error": { "code": "FDS_BLOCKED", "message": "이상거래가 의심되어 이체를 차단했습니다.", "details": [],
  "extra": { "fds_log_id": 7, "risk_level": "HIGH", "ml_score": 0.9754,
    "rule_hits": [{ "code": "NEW_DEVICE", "name": "처음 보는 기기", "level": "MEDIUM" },
                  { "code": "CONVERSATION_AI_SCAM", "name": "AI가 대화를 보이스피싱으로 판단", "level": "HIGH",
                    "detail": "가족을 사칭해 급히 송금을 요구하고 있어요." }],
    "top_factors": [{ "feature": "is_new_device", "label": "새 기기", "contribution": 5.648 }],
    "warning": "금융기관·검찰·경찰·금융감독원은 전화나 메시지로 송금을 요구하지 않습니다. ..." } } }
```

- 1일 한도는 한국 시간 0시부터의 `TRANSFER_OUT` 합계로 계산합니다. 본인 적금·예금 납입은 한도에 포함하지 않습니다.
- 받는 계좌가 등록된 수취인이면 `recipients.last_sent_at`이 갱신됩니다. 등록 안 된 계좌는 자동 등록하지 않습니다.

`POST /transfers/savings`: `amount`를 생략하면 월 납입액
```json
{ "from_checking_account_id": 1, "savings_account_id": 1 }
```
`POST /transfers/deposit`
```json
{ "from_checking_account_id": 1, "deposit_account_id": 1, "amount": 1000000 }
```
실패: 위 공통 + `400 ACCOUNT_MATURED` (만기 지난 계좌)
</details>

## cards: 카드 (`domains/cards`)

`{type}` = `credit` · `debit`

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | GET | `/cards` | 🔒 | 내 카드 전체 |
| ✅ | POST | `/cards/credit` | 🔒 | 신용카드 발급 (`checking_account_id` = 결제 계좌) |
| ✅ | POST | `/cards/debit` | 🔒 | 체크카드 발급 (`checking_account_id` = 출금 계좌) |
| ✅ | GET | `/cards/{type}/{card_id}` | 🔒 | 카드 상세 |
| ✅ | GET | `/cards/{type}/{card_id}/histories` | 🔒 | 사용내역 |
| ✅ | POST | `/cards/{type}/{card_id}/payments` | 🔒 | 결제(사용) 등록. 체크카드는 연결 계좌에서 바로 출금 |

<details>
<summary>요청 예시</summary>

`POST /cards/credit`
```json
{ "product_id": 1, "checking_account_id": 1, "payment_date": 14 }
```
`POST /cards/debit/1/payments`
```json
{ "place_of_use": "편의점", "used_amount": 12000 }
```
실패: `400 PRODUCT_TYPE_MISMATCH`, `400 INSUFFICIENT_BALANCE`(체크카드), `403 CARD_FORBIDDEN`, `404 CARD_NOT_FOUND`
</details>

## recipients: 수취인 (`domains/recipients`)

에이전트가 "엄마한테 보내줘"의 "엄마"를 계좌번호로 바꾸는 데 쓰고, FDS의 "신규 수취인" 판정 기준이 됩니다.

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | GET | `/recipients?nickname=` | 🔒 | 내 수취인 목록 (최근 보낸 순). `nickname`을 주면 그 별칭만 |
| ✅ | POST | `/recipients` | 🔒 | 등록. 입출금 계좌번호만 가능, 예금주 이름은 자동으로 채움 |
| ✅ | PATCH | `/recipients/{recipient_id}` | 🔒 | 별칭 변경 |
| ✅ | DELETE | `/recipients/{recipient_id}` | 🔒 | 삭제 → `204` |

<details>
<summary>요청 예시</summary>

`POST /recipients`
```json
{ "account_num": "110-555-000111", "nickname": "엄마" }
```
실패: `404 ACCOUNT_NOT_FOUND`, `409 RECIPIENT_ALREADY_EXISTS`(같은 계좌), `409 RECIPIENT_NICKNAME_EXISTS`(같은 별칭)
</details>

---

## fds: 이상거래 탐지 (`domains/fds`)

판정 로직은 `POST /transfers` 안에서 돌고, 여기서는 기록만 조회합니다. 규칙·피처·모델은 [fds_training/results.md](../fds_training/results.md) 참고.

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | GET | `/fds/logs?limit=50` | 🔒 | 내 FDS 판정 기록 (최근 순). 통과·추가 인증·차단 모두 |

## chat: AUI 에이전트 대화 (`domains/chat`, `agents/`)

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/chat/sessions` | 🔒 | 대화 시작 → `session_id` |
| ✅ | POST | `/chat/sessions/{session_id}/messages` | 🔒 | 에이전트에게 말하기 `{ "text", "input_mode": "text" \| "voice" }` → 사용자 메시지 + 답변 |
| ✅ | GET | `/chat/sessions/{session_id}/messages` | 🔒 | 대화 기록 (오래된 순) |

<details>
<summary>응답 예시와 카드 종류</summary>

`POST /chat/sessions/{id}/messages` `{ "text": "엄마한테 오만원 보내줘", "input_mode": "voice" }` → `200`
```json
{ "data": {
  "user_message": { "msg_id": 1, "role": "user", "content": "엄마한테 오만원 보내줘", "intent": "transfer", "input_mode": "voice", "card": null, "created_at": "..." },
  "assistant_message": { "msg_id": 2, "role": "assistant", "content": "엄마(김영희)님께 5만원을 보낼까요? 화면의 확인 카드에서 승인을 눌러 주세요.",
    "card": { "type": "transfer_confirmation", "from_checking_account_id": 1, "from_account_num": "110-...", "from_nickname": "생활비", "from_balance": 1200000,
      "to_account_num": "110-...", "holder_name": "김영희", "recipient_nickname": "엄마", "amount": 50000, "amount_text": "5만원",
      "insufficient_balance": false, "confirmation_token": "eyJ...", "expires_at": "...",
      "tts_text": "엄마님께 5만원을 보냅니다. 승인하시겠어요?" } } } }
```

| `card.type` | 언제 | 프론트가 할 일 |
|---|---|---|
| `transfer_confirmation` | 이체 정보가 다 모였을 때 | 승인/취소 버튼. 승인하면 카드 값 + `session_id` + `confirmation_token`으로 `POST /transfers`. `tts_text`를 읽음 |
| `account_summary` | 잔액·계좌 조회 | `accounts` 목록 표시 (계좌번호는 뒤 4자리) |

실패: `503 LLM_UNAVAILABLE`(Gemini 키 없음·호출 실패), `403 CHAT_SESSION_FORBIDDEN`, `404 CHAT_SESSION_NOT_FOUND`
</details>

## voice: 목소리 등록·음성 승인 (`domains/speech`)

설계·확인 결과·한계: [VOICE_AUTH.md](VOICE_AUTH.md). 녹음은 모두 16kHz 모노 16bit WAV (multipart).

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | GET | `/voice/profile` | 🔒 | `{ enrolled, available, created_at, updated_at }`. `available`=false면 서버가 음성 승인을 못 함 |
| ✅ | POST | `/voice/profile` | 🔒 | 등록·재등록. form: `password`, `consent=true`, `recordings` × 3 |
| ✅ | DELETE | `/voice/profile` | 🔒 | 삭제 `{ "password" }` → `204` |
| ✅ | POST | `/voice/approvals` | 🔒 | form: `session_id`, `confirmation_token`, `recording` → `{ voice_approval_token }` (2분, 그 카드에만 유효) |

확인 카드(`transfer_confirmation`)에 `voice_enrolled`, `voice_challenge`("895"), `voice_challenge_text`("팔 구 오")가 추가됩니다.

실패: `400 VOICE_DIGITS_MISMATCH` / `400 VOICE_NOT_MATCHED` (`extra.remaining_attempts`), `400 VOICE_LOCKED`(카드당 2번 실패), `400 INVALID_AUDIO`, `400 CONSENT_REQUIRED`, `401 INVALID_CREDENTIALS`, `404 VOICE_NOT_ENROLLED`, `503 VOICE_UNAVAILABLE`(모델·키 없음, 15초 초과)

## MCP 서버 (`mcp_servers/`)

AUI 에이전트와 외부 MCP 클라이언트가 쓰는 도구 서버입니다 (streamable HTTP, `Authorization: Bearer <JWT>`). 도구 목록과 안전 규칙: [MCP_SERVERS.md](MCP_SERVERS.md)

| 경로 | 서버 | 도구 수 |
|---|---|---|
| `/mcp/accounts/mcp` | 계좌 | 8 |
| `/mcp/transfers/mcp` | 이체·수취인 | 7 |
| `/mcp/products/mcp` | 상품 | 2 |
| `/mcp/cards/mcp` | 카드 | 4 |
| `/mcp/security/mcp` | FDS 기록·음성 승인 상태 | 2 |

## 새 API를 추가하는 순서

1. `schemas.py`: 요청·응답 모양 정의
2. `repository.py`: 필요한 DB 조회·저장 메서드
3. `service.py`: 규칙 검사와 처리 (돈이 움직이면 `async with db.begin():`)
4. `router.py`: 경로 연결, `SuccessResponse[...]`로 감싸서 반환
5. `tests/`에 테스트 추가
6. 이 문서의 상태를 📝 → ✅로 변경
