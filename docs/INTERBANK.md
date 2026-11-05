# 다른 은행 이체 (ClearingHub 연동)

AvengersBank는 은행 간 이체 중계 서버 [ClearingHub](https://github.com/jjh7757/clearing-hub)의 참가 은행이다. 연동 규격은 ClearingHub 저장소의 `docs/SPEC.md` (v0.1). 다른 은행 서버를 직접 부르지 않고 허브만 부른다.

```
AvengersBank ──POST /v1/inquiry · /v1/transfers · GET /v1/transfers/{id}──▶ ClearingHub ──▶ 다른 은행
AvengersBank ◀──POST /interbank/inquiry · /interbank/receive · GET /interbank/receive/{id}── ClearingHub ◀── 다른 은행
```

## 동작 방식: 받기는 푸시, 결과 확인은 폴링

| 방향 | 방식 | 누가 부르나 |
|---|---|---|
| 받기 (다른 은행 → 우리) | **푸시** | 허브가 우리 `/interbank/*`를 부른다 |
| 보낸 이체의 결과 확인 | **폴링** | 우리 `worker.py`가 30초마다 허브 `GET /v1/transfers/{id}`를 부른다 (허브에는 콜백이 없음) |

- **우리 서버는 항상 켜져 있어야 한다.** 허브가 언제 입금을 보낼지 모르기 때문이다. 별도 대기 작업은 필요 없고, 원래 떠 있는 FastAPI 서버에 `/interbank/*` 경로가 있으면 된다.
- **허브가 닿을 수 있는 주소여야 한다.** `127.0.0.1`은 외부 허브가 부를 수 없으므로, 실제로 입금을 받으려면 공인 주소에 배포하고 그 주소를 허브에 등록한다 (로컬 테스트는 허브도 로컬에 띄운다).
- **5초 안에 응답해야 한다** (허브 → 은행 타임아웃, SPEC).
- **우리 서버가 잠깐 꺼져 있어도 돈은 사라지지 않는다.** 허브는 타임아웃·`5xx`일 때 보낸 은행에 `202 PENDING`을 주고, 1분 간격으로 최대 10번 같은 `transfer_id`로 다시 보낸다 (그 전에 `GET /interbank/receive/{id}`로 이미 입금했는지 먼저 묻는다). 10번 넘게 실패하면 `UNKNOWN`이 되고 허브 관리자가 확인한다. `4xx`는 최종 거절이라 재시도하지 않는다.
- 재시도가 안전한 것은 받는 쪽이 `transfer_id`로 한 번만 입금하기 때문이다 (아래 "받기").

## 설정

허브 관리자에게 은행 이름과 입금 API 주소(`https://<우리 도메인>/api/interbank`, 로컬은 `http://127.0.0.1:8000/interbank`)를 알려 주고 받은 값을 `.env`에 넣는다.

| 이름 | 값 |
|---|---|
| `BANK_CODE` | 허브가 배정한 우리 은행 코드 (기본 `901`) |
| `HUB_URL` | 허브 주소 (`/v1` 없이) |
| `HUB_API_KEY`, `HUB_SECRET` | 허브가 발급한 API 키와 서명 비밀키. secret은 허브가 우리에게 보내는 요청 검증에도 쓴다 |
| `CI_KEY` | 가상 CI 키 (다른 은행 내 계좌, 아래). 허브 관리자가 secret과 같은 경로로 준다. 없으면 이 기능만 꺼진다 (`503 INTERBANK_UNAVAILABLE`) |

셋(`HUB_URL`, `HUB_API_KEY`, `HUB_SECRET`) 중 하나라도 없으면 타행 이체가 꺼진다: `to_bank`가 다른 은행이면 `503 INTERBANK_UNAVAILABLE`, `/interbank/*`는 `503 INTERBANK_DISABLED`. 처리 중 확인 태스크도 돌지 않는다.

## 보내기: `POST /transfers` + `to_bank`

`transfers/service.py`의 `_transfer_interbank`, 돈 흐름은 `interbank/service.py`.

1. **예금주 확인** (`POST /v1/inquiry`). 계좌가 없거나 허브가 응답하지 않으면 여기서 끝. 출금하지 않는다
2. **[트랜잭션] 한도·FDS → 출금**. 잔액, 1회·1일 한도, FDS는 자행 이체와 같다. 통과하면 잔액을 빼고 `TRANSFER_OUT` 거래내역과 `interbank_transfers`(상태 `PENDING`)를 함께 커밋한다
3. **허브에 이체 요청** (`POST /v1/transfers`, `transfer_id`는 우리가 만든 UUID)

| 허브 응답 | 처리 | 사용자 응답 |
|---|---|---|
| `200 COMPLETED` | `COMPLETED` | `200`, `status: "COMPLETED"` |
| `4xx` (받는 은행 거절 등) | 잔액을 되돌리고 `TRANSFER_REFUND` 거래내역, `FAILED` | `400 INTERBANK_FAILED` (`extra.balance_after`) |
| `202 PENDING`, 5xx, 응답 없음 | **그대로 `PENDING`** | `200`, `status: "PENDING"`, "확인 중" |

4. **처리 중 확인** (`interbank/worker.py`, 30초마다 `confirm_pending`): `GET /v1/transfers/{id}`
   - `COMPLETED` → 완료, `FAILED` → 되돌림
   - `404`(허브가 모름 = 요청이 닿지 않았음) → 같은 `transfer_id`로 다시 보낸다 (허브·받는 은행이 멱등이라 두 번 들어가지 않음)
   - 그 밖(허브도 `PENDING`/`UNKNOWN`, 응답 없음) → 다음에 다시

**결과를 모르는 채로 되돌리지 않는다.** 되돌렸는데 받는 은행에 실제로 입금됐다면 돈이 두 배가 된다. 그래서 응답 없음은 실패가 아니라 `PENDING`이다. `PENDING`인 `interbank_transfers` 행이 "타행 송금 중간 계정" 역할을 한다 (출금됐지만 아직 확정되지 않은 돈).

**FDS**: 받는 계좌는 `902:110-123-0001`처럼 은행 코드를 붙여 넘긴다. 우리 은행의 같은 번호 계좌(등록 수취인)로 착각해 "처음 보내는 계좌" 검사를 건너뛰지 않게 하기 위해서다. 그래서 타행 계좌는 지금은 항상 처음 보내는 계좌로 본다 (수취인 등록에 은행이 없음).

**1일 한도**: 되돌려 받은 `TRANSFER_REFUND`는 오늘 보낸 금액에서 뺀다.

## 받기: `/interbank/*` (허브 전용)

`interbank/router.py`. 허브 요청인지 `X-Bank-Code: 000` + `HUB_SECRET` 서명으로 확인한다. 응답은 SPEC 5절 형식(`{"error", "message"}`)이다 (앱의 기본 오류 형식이 아님). 처리하지 못한 예외도 `500 {"error": "INTERNAL_ERROR"}`로 답한다(`SpecErrorRoute`, 로그·Sentry에는 남김). 허브는 5xx면 재시도하고 입금은 `transfer_id`로 멱등이다.

| 경로 | 처리 |
|---|---|
| `POST /interbank/inquiry` | 입출금 계좌번호 → 예금주 이름 / `404 ACCOUNT_NOT_FOUND` |
| `POST /interbank/receive` | 입금 + `TRANSFER_IN` 거래내역 + `interbank_receipts`를 한 트랜잭션으로. **같은 `transfer_id`는 입금하지 않고 같은 응답** (동시에 두 번 와도 기본 키 충돌로 한 번만) |
| `GET /interbank/receive/{id}` | 입금했으면 `200 COMPLETED`, 아니면 `404 TRANSFER_NOT_FOUND` (허브가 다시 보낸다) |

## 이체 화면 (`/transfer`)

`frontend/src/pages/TransferPage.tsx`. 모아 없이 직접 보내는 화면이다. 내 계좌 → "이체하기", 입출금 계좌 상세 → "이 계좌에서 이체하기"로 들어온다.

1. 입력: 출금 계좌, 받는 은행(우리 은행 + `GET /transfers/banks`), 계좌번호, 금액(+1만·+5만·+10만·전액)
2. "다음" → `POST /transfers/inquiry`로 **받는 분 이름을 먼저 보여 준다** (다른 은행이면 허브에 물음, 돈은 안 움직임). 계좌가 없으면 입력 화면에 오류
3. "보내기" → `POST /transfers`. FDS가 PIN을 요구하면 PIN 입력, 차단하면 경고(`FdsAlert`). 결과는 완료 / "확인 중"(PENDING, 출금됐고 받는 은행 확인 중) / 되돌림(`INTERBANK_FAILED`)
4. 아래 "다른 은행 이체" 목록: 확인 중·완료·돌려받음, 새로고침

허브를 쓸 수 없으면(설정 없음·응답 없음) 받는 은행에 우리 은행만 나오고 안내 문구를 보여 준다. 화면 이체는 확인 카드(채팅)를 거치지 않으므로 목소리 등록 사용자의 음성 승인·PIN 요구는 없고, FDS 판정(MEDIUM이면 PIN)만 적용된다 (자행 이체 화면과 같은 규칙).

로컬에서 확인: `.claude/launch.json`의 `hub-8010`(ClearingHub, `local_hub.db`), `banksim-8100`(가짜 은행), `backend-8001-hub`(허브 설정을 넣은 백엔드), `frontend-8001`. 허브 DB는 901·902를 고정 테스트 키로 등록한 시드로 만든다.

## 모아 대화

"SimBank 110-123-0001로 5만원 보내줘"도 자행 이체와 같은 확인 카드로 처리한다 (`agents/graph.py`).

1. 의도 분류기(Gemini)가 `bank_name`("SimBank")을 뽑는다. 이체 노드가 MCP `find_bank`로 은행 코드를 찾는다 (대소문자·띄어쓰기·"은행"은 무시, 우리 은행 이름이면 자행). 없으면 보낼 수 있는 은행 목록과 함께 되묻는다
2. 다른 은행은 **계좌번호로만** 보낸다 (등록 수취인·내 계좌는 우리 은행에만 있다). 번호가 없으면 금액은 기억하고 "SimBank 계좌번호를 알려 주세요". 예금주는 `find_account_holder(bank_code=...)`로 허브에 확인한다
3. `prepare_transfer(to_bank=...)` → 확인 카드에 `to_bank`, `to_bank_name`, 받는 분 "SimBank 김철수". **승인 토큰에도 은행 코드(`bk`)가 들어간다**
4. 카드 승인 → 앱이 카드의 `to_bank`를 그대로 실어 `POST /transfers`. 서버는 토큰의 은행과 요청의 은행이 다르면 `CONFIRMATION_MISMATCH` (같은 번호의 우리 은행 계좌로 바꿔치기 방지). 음성 승인·PIN, 대화 위험 판별(FDS), 카드 1회 사용은 자행 이체와 같다
5. 결과가 PENDING이면 카드에 "확인 중"과 이체 화면 링크를 보여 준다

실제 Gemini 확인 (로컬, 실제 허브·가짜 은행): "SimBank 110-123-0001로 3만원 보내줘" → "생활비 통장에서 SimBank 김철수님께 3만원을 보낼까요?" → 승인 → 완료. "SimBank로 2만원 보내고 싶어" → "SimBank 계좌번호를 알려 주세요." → "110-123-0005" → 2만원 카드 → 승인 → "확인 중".

## 다른 은행 내 계좌 (SPEC 9절)

고객 동의를 받아 같은 사람 명의로 다른 참가 은행에 있는 계좌를 불러오고, 그 계좌로 보낸다. 실제 금융권의 CI(연계정보) 대신 **가상 CI**를 쓴다.

```
ci = hex(HMAC-SHA256(CI_KEY, 이름(공백 제거, NFC) + "|" + 생년월일(YYYYMMDD) + "|" + 휴대폰번호(숫자만)))
```

- **저장**: `users.birth_date`(선택), `users.ci`(인덱스). 가입·`PATCH /users/me`에서 이름·휴대폰·생년월일이 바뀌면 다시 계산한다 (`users/ci.py`). 생년월일이나 `CI_KEY`가 없으면 `ci`는 비어 있다
- **불러오기** `POST /transfers/own-accounts {"consent": true}` (`interbank/service.py`의 `lookup_own_accounts`)
  1. 생년월일이 없으면 `400 BIRTH_DATE_REQUIRED` (화면이 생년월일을 받아 저장하고 다시 부른다)
  2. 동의 기록 `own_account_lookups`(`consent_id = avb-<uuid>`)를 먼저 커밋하고, 허브 `POST /v1/accounts/lookup {ci, consent_id}`. 원본 개인정보는 보내지 않는다
  3. 허브가 준 계좌(가린 번호 + `account_ref`)를 `own_account_refs`에 **이 사용자에게 묶어** 29분 저장 (허브는 30분). 같은 은행의 다른 고객이 남의 ref를 쓰지 못하게 하기 위해서다
  4. 허브 `429` → `429 TOO_MANY_LOOKUPS`, 그 밖의 실패 → `503`
- **보내기** `POST /transfers`에 `to_account_ref` (+ `to_bank`, `to_account_num`에는 가린 번호)
  - ref가 내 것·은행 일치·만료 전인지 확인 → 아니면 `400 ACCOUNT_REF_INVALID`. 채팅(`session_id`)이나 우리 은행으로는 못 쓴다 (`ACCOUNT_REF_NOT_ALLOWED`)
  - 받는 분 조회(허브 `/v1/inquiry`)는 건너뛴다. 허브가 같은 사람으로 확인해 준 계좌라서다. 예금주는 내 이름으로 저장했다가 허브 응답의 이름으로 바뀐다
  - 허브에는 `to_account` 대신 `to_account_ref`를 보낸다 (`interbank_transfers.to_account_ref`, 확인 태스크의 재전송도 같다). `to_account`에는 가린 번호가 남는다
  - **FDS**: 내 계좌로 본다 (`to_own_account`). 처음 보내는 계좌·심야 고액·잔액 대부분 규칙에 걸리지 않는다
- **받기(허브 → 우리)** `POST /interbank/accounts {ci}`: 이 CI 고객의 입출금 계좌(`account_num`, `product_name`). 고객이 없어도 `200 {"accounts": []}`. 조회마다 `hub_account_queries`에 시각·`ci`·돌려준 계좌 수를 남긴다 (SPEC 9.4 규칙 5, 고객이 없던 조회도 0개로)
- **화면**: 이체 화면의 "다른 은행 내 계좌 불러오기" → 동의 체크 → (생년월일) → 목록에서 고르면 받는 은행·가린 번호가 채워지고 "내 계좌" 표시 (`components/OwnAccountsPanel.tsx`)

확인: `tests/test_own_accounts.py` (8개: 생년월일 필요, 동의 필수, 불러오기 → 허브에 CI만 감 → ref 이체 → FDS LOW, 남의 ref·다른 은행·우리 은행·채팅·만료 거절, 허브 429·장애·키 없음, 프로필 변경 시 CI 재계산, 가입 시 생년월일, `/interbank/accounts`). 브라우저(로컬, 실제 ClearingHub + 가짜 은행을 한 프로세스로): 김철수 고객 → 동의 → 생년월일 입력 → SimBank 계좌 2개 → 급여통장 선택 → 3만 원 완료, 허브 거래의 받는 계좌가 실제 번호 `110-456-0001`로 풀린 것 확인

## 테이블

| 테이블 | 용도 |
|---|---|
| `interbank_transfers` | 보낸 타행 이체: transfer_id, user_id, 출금 계좌, to_bank, to_account, 예금주, 금액, status, fail_code/message, check_count |
| `interbank_receipts` | 받은 타행 입금: transfer_id(멱등 키), 입금 계좌, 보낸 은행·계좌·이름, 금액 |
| `own_account_lookups` | 다른 은행 내 계좌 불러오기 동의 기록: consent_id, user_id, 허브 lookup_id, 계좌 수 |
| `own_account_refs` | 허브가 준 account_ref를 사용자에게 묶음: 은행, 가린 번호, 상품명, 만료 |

거래내역 `type`에 `TRANSFER_REFUND`(타행 이체 되돌림, +)를 추가했다.

## 확인한 것

- 브라우저(로컬, 실제 허브·가짜 은행 서버): SimBank `0001` 5만 원 → 받는 분 "김철수" 확인 → 완료, 잔액 반영 / `0005`(입금됐는데 응답 늦음) → "확인 중" → 허브·우리 확인 태스크가 돈 뒤 새로고침하면 "완료" / `0002` → 입력 화면에 "받는 계좌를 찾을 수 없습니다", 출금 없음. 가짜 은행 입금은 건마다 1번
- `tests/test_interbank.py` (17개): 받는 분 이름 확인(우리 은행·다른 은행·없는 계좌·없는 은행), 가짜 허브로 완료, 예금주 조회 실패 시 출금 안 함, 받는 은행 거절 → 되돌림 + 한도 복구, PENDING → 확정/실패, 허브 무응답 → PENDING 유지 → 같은 ID 재전송, 잔액 부족, 자행 코드는 자행 이체, 입금 멱등, 오류 형식, 서명 거절. 모아 대화: 카드 → 은행을 빼고 승인하면 거절 → 은행 넣어 승인 → 완료 → 재사용 거절, 계좌번호 되묻기(금액 기억), 없는 은행·없는 계좌, PENDING 승인, 대화 속 "검찰·안전계좌"가 타행 이체에도 FDS로 걸림
- 실제 ClearingHub + bank_sim 코드와 한 프로세스에서 왕복: 정상 입금, 계좌 없음, "입금됐는데 응답 없음"(`0005`) → 허브 확인 → 우리 확인 → 둘 다 `COMPLETED`·입금 1번, 반대 방향(다른 은행 → 허브 → 우리) 입금과 재전송 시 1번만 입금

## 다음 단계

- 수취인 등록에 은행 코드 (타행 수취인도 "처음 보내는 계좌" 검사를 건너뛸 수 있게)
- (완료) 배포 서버 허브 연결: [DEPLOY.md](DEPLOY.md)의 "타행 이체: ClearingHub 연결"
