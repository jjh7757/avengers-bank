# 보안: 인증·이체 보호

금융 서비스에서 기본으로 갖추는 보호 장치와, 이 프로젝트에서 어떻게 만들었는지 정리한다.

| 장치 | 막는 것 | 위치 |
|---|---|---|
| access 토큰은 메모리, refresh 토큰은 httpOnly 쿠키 | XSS로 토큰 훔치기 | `domains/users`, `frontend/src/api/client.ts` |
| refresh 토큰 회전 + 재사용 감지 | 훔친 refresh 토큰으로 계속 접속 | `UserService.refresh` |
| 지난 로그인 표시 | 모르는 접속을 알아채지 못함 | 설정 화면 |
| 로그인 실패 제한 | 비밀번호 무차별 대입 | `core/rate_limit.py` |
| 이체 요청·PIN 오류 제한 | 자동화된 반복 이체, PIN 대입 | `core/rate_limit.py`, `transfers/router.py` |
| 이체 멱등성 (`Idempotency-Key`) | 버튼 두 번·네트워크 재시도로 두 번 출금 | `domains/transfers/idempotency.py` |
| 보안 키패드 (숫자 배열 섞기) | 어깨 너머 보기, 누른 위치로 PIN 추측 | `frontend/src/components/PinPad.tsx` |
| 자동 로그아웃 (10분, 1분 전 경고) | 자리를 비운 사이 남이 조작 | `frontend/src/components/IdleGuard.tsx` |
| 관리자 역할(CLI로만 부여)·매 요청 DB 확인·감사 로그 | 회원가입으로 관리자 되기, 강등 뒤 남은 토큰, 기록 없는 자금 이동 | `domains/admin`, `core/dependencies.py` `require_admin` |

## 로그인 유지 (access / refresh 토큰)

```
로그인 ──▶ access 토큰(15분, 응답 본문 → 메모리)  +  refresh 토큰(14일, httpOnly 쿠키)
API 401 ──▶ POST /users/refresh (쿠키) ──▶ 새 access 토큰 + 새 refresh 쿠키, 예전 refresh 폐기
새로고침 ──▶ 메모리가 비었으므로 처음에 /users/refresh로 되살린다
로그아웃 ──▶ POST /users/logout: refresh 폐기, 쿠키 삭제
```

- 쿠키: `HttpOnly`(자바스크립트가 못 읽음), `SameSite=Strict`(다른 사이트에서 보낸 요청에는 안 붙음), `Secure`(HTTPS만), `Path=/`.
  로컬 http에서 테스트할 때만 `REFRESH_COOKIE_SECURE=false` (브라우저는 `http://localhost`를 안전한 곳으로 봐서 개발 중에는 켜 둬도 된다).
- DB(`refresh_tokens`)에는 토큰의 SHA-256 해시만 둔다. DB가 새어도 쿠키 값을 만들 수 없다.
- **재사용 감지:** 회전으로 폐기된 토큰이 다시 오면 누군가 훔쳐 쓴 것으로 보고 그 사용자의 refresh 토큰을 모두 끊는다(`401 REFRESH_TOKEN_REUSED`).
  단, 폐기 20초 안(`REFRESH_REUSE_GRACE_SECONDS`)에 다시 오면 탭 여러 개가 동시에 갱신한 것으로 보고 새 토큰을 하나 더 준다.
  이 유예는 회전(`revoke_reason = rotated`)에만 적용되고, 로그아웃·재사용으로 끊은 토큰에는 없다.
- access 토큰은 폐기 목록이 없으므로 로그아웃 뒤에도 최대 15분은 유효하다. 짧게 둔 이유다.

## 요청 제한

| 대상 | 기준 | 넘으면 |
|---|---|---|
| 로그인 실패 (아이디별) | 10분에 5번 | `429 TOO_MANY_LOGIN_ATTEMPTS` (맞는 비밀번호도 막힘). 성공하면 초기화 |
| 로그인 실패 (IP별) | 10분에 20번 | 같은 코드. 아이디를 바꿔 가며 시도하는 것 |
| 이체 요청 (사용자별) | 1분에 20번 | `429 TOO_MANY_TRANSFER_REQUESTS` |
| 이체 PIN 오류 (사용자별) | 30분에 5번 | `429 PIN_LOCKED`. 이체가 성공하면 초기화 |

모든 429에는 `Retry-After` 헤더와 `error.extra.retry_after_seconds`가 붙는다.
서버 한 대(컨테이너 1개)라 메모리에 센다. 서버를 여러 대로 늘리면 Redis 같은 공유 저장소로 옮겨야 하고, 서버를 다시 켜면 횟수가 초기화된다.

## 이체 멱등성

앱은 이체 한 건(확인 화면·확인 카드 하나)마다 `crypto.randomUUID()`로 키를 만들어 `Idempotency-Key` 헤더에 싣는다.
PIN을 넣고 다시 보내거나 네트워크 때문에 다시 보낼 때는 같은 키를 쓴다.

| 같은 키로 다시 왔을 때 | 응답 |
|---|---|
| 처음 요청이 성공했다 | 저장해 둔 처음 응답 그대로 + `Idempotent-Replayed: true`. 돈은 다시 움직이지 않는다 |
| 처음 요청이 아직 처리 중 | `409 IDEMPOTENCY_IN_PROGRESS` |
| 내용(계좌·금액·은행·대화)이 다르다 | `422 IDEMPOTENCY_KEY_REUSED` |
| 처음 요청이 실패했다 (PIN 필요, 잔액 부족 등) | 키가 풀려 있어 새 요청처럼 처리한다 |

- 키는 사용자별로 따로 센다 (`(user_id, key)` 유일). 24시간이 지나면 지운다.
- 비교하는 내용에 PIN·승인 토큰·기기 정보는 넣지 않는다. 재시도 때 달라질 수 있고 비밀이라서다.
- 한계: 이체 커밋과 결과 저장은 별도 트랜잭션이다. 그 사이에 서버가 죽으면 키가 "처리 중"으로 남아 같은 키 재시도는 409를 받는다.
  자동으로 다시 보내지 않으므로 두 번 출금되지는 않고, 사용자는 거래내역으로 확인한다.
- 헤더는 선택이다. 없으면 예전처럼 처리한다 (MCP·스크립트 호환).

## 관리자

- **역할:** `users.role` = `CUSTOMER`(기본) / `ADMIN`. 회원가입·`PATCH /users/me`는 `role`을 받지 않는다(본문에 넣어도 무시).
  관리자는 서버 CLI로만 만든다: `python -m avengers_bank.domains.admin.cli create-admin <아이디> --name … --phone …`
  (비밀번호는 터미널이면 묻고, 아니면 `ADMIN_PASSWORD`. 8자 이상). 고객 아이디를 관리자로 올리지 않고 따로 만든다. `revoke-admin`은 고객으로 강등, `list-admins`
- **확인:** `/admin/*`는 `require_admin`. 토큰에 역할을 넣지 않고 `get_current_user`가 매 요청 DB에서 읽은 값을 본다.
  그래서 강등하면 이미 발급한 access 토큰(최대 15분)으로도 바로 `403 ADMIN_REQUIRED`다
- **할 수 있는 것:** 은행이 가진 돈(금고 현금 `CASH_VAULT` ↔ 허브 예치금 `HUB_RESERVE`)만 움직인다. 그것도 허브 관리자가 승인해야 한다.
  고객 계좌 잔액을 바꾸는 관리자 API는 없다 (테스트 `test_admin_treasury.py`가 신청·승인 뒤 고객 잔액이 그대로인지 본다)
- **감사 로그 `admin_audit_logs`:** 신청·취소·동기화마다 관리자, 행동, 대상(신청 id), 내용(kind·amount·memo·결과 상태), `OK`/`FAILED`와 오류 코드, IP, 시각.
  **실패한 시도도 남긴다**: 본 작업이 예외로 끝나면 그 트랜잭션을 롤백한 뒤 기록만 따로 커밋한다 (이체 FDS 거절 기록과 같은 방식).
  지우거나 고치는 API는 없다. 조회는 `GET /admin/audit-logs`. 권한 없는 시도(401·403)는 관리자 행동이 아니라 남기지 않는다
- **maker-checker(두 사람 결재)를 두지 않은 이유:** 예치금은 은행이 신청하고 허브(중앙은행 역할) 관리자가 승인해야 움직이므로 이미 두 단계다.
  실제 은행이라면 신청 전에 은행 안 결재(담당자 기안 → 책임자 승인)가 하나 더 있고, 신청자와 승인자가 같은 사람이면 막는다.
  이 프로젝트는 관리자 한 명으로 시연하므로 감사 로그로 누가 무엇을 했는지 남기는 데서 멈췄다
- **한계:** 관리자도 로그인은 고객과 같은 `/users/login`(같은 실패 제한)이다. 2단계 인증·접속 IP 제한은 없다

## 화면

- **보안 키패드:** 이체 PIN 입력(이체 화면, 모아 확인 카드, 한도 올리기, PIN 등록)은 숫자 배열이 매번 바뀌는 키패드로 받는다. 입력은 점으로만 보이고, 키패드에 초점이 있으면 물리 키보드 숫자·Backspace도 받는다.
- **자동 로그아웃:** 10분 동안 조작(클릭·키·스크롤·터치)이 없으면 1분 전에 경고 창을 띄우고, "계속 이용하기"를 누르지 않으면 로그아웃한다. 다른 탭에서 쓰고 있으면 유지되고(localStorage로 마지막 조작 시각 공유), 절전에서 깨어나면 지난 시간을 다시 잰다. 로그인 화면에 이유를 보여 준다.
- **지난 로그인:** 설정 맨 위에 바로 전 로그인 시각을 보여 준다.
- **정책·안내:** `/privacy`(개인정보처리방침), `/support`(고객센터·FAQ·보이스피싱 안내), `/about`(버전·오픈소스 라이선스). 로그인하지 않아도 볼 수 있다.

## 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `JWT_EXPIRE_MINUTES` | 15 | access 토큰 유효 시간 (예전 기본값 30에서 줄임) |
| `REFRESH_TOKEN_DAYS` | 14 | 로그인 유지 기간 |
| `REFRESH_COOKIE_SECURE` | true | refresh 쿠키 `Secure`. HTTPS 운영에서는 꼭 켠다 |
| `REFRESH_REUSE_GRACE_SECONDS` | 20 | 동시 갱신으로 보는 시간 |
