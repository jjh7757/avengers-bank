# 프로젝트 구조

FastAPI + SQLAlchemy(async) + Alembic. 업무별로 **도메인 폴더**를 나누고, 각 도메인 안은 같은 5개 파일로 구성합니다.

## 전체 트리

```
avengers-bank/
├── .env.example            # 환경변수 예시 → .env로 복사해서 사용 (.env는 커밋 금지)
├── pyproject.toml          # 의존성 (uv)
├── uv.lock
├── alembic.ini
├── alembic/                # DB 마이그레이션
│   ├── env.py              # 모든 models.py를 import해서 테이블 정보를 모음
│   └── versions/           # 마이그레이션 파일이 쌓이는 곳
├── docs/                   # 팀 공유 문서 (ERD, API, 구조)
├── tests/                  # pytest (SQLite로 실행, DB 서버 불필요)
│   ├── conftest.py
│   └── test_users.py
└── src/avengers_bank/
    ├── main.py             # 앱 생성, CORS, 예외 핸들러, 라우터 등록
    ├── core/               # 모든 도메인이 같이 쓰는 공용 코드
    │   ├── config.py       # .env 읽기
    │   ├── database.py     # DB 연결, Base, get_db
    │   ├── security.py     # 비밀번호 해시, JWT
    │   ├── dependencies.py # get_current_user (로그인 사용자 확인)
    │   ├── exceptions.py   # BadRequest/Unauthorized/Forbidden/NotFound/Conflict
    │   ├── exception_handlers.py
    │   └── responses.py    # SuccessResponse, ErrorResponse 형식
    └── domains/
        ├── users/          # 회원가입, 로그인, 내 정보          ✅ 구현됨
        ├── products/       # 계좌·카드 상품 조회                📝 모델만
        ├── accounts/       # 입출금·예금·적금 계좌, 거래내역      📝 모델만
        ├── transfers/      # 이체, 적금 납입, 예금 입금 (테이블 없음) 📝
        └── cards/          # 신용·체크카드, 사용내역, 결제       📝 모델만
```

## 도메인 안의 5개 파일

```
요청 → router → service → repository → DB
              (schemas, models는 옆에서 사용)
```

| 파일 | 역할 | 비유 |
|---|---|---|
| `router.py` | URL을 받아서 service를 호출하고 응답을 감쌈 | 창구 직원: 접수만 |
| `service.py` | 규칙 검사, 처리 순서, 트랜잭션 | 팀장: "잔액 충분해? 한도 넘었어?" |
| `repository.py` | DB 조회·저장만 | 금고 담당 |
| `models.py` | DB 테이블 정의 (SQLAlchemy) | 장부 양식 |
| `schemas.py` | 요청·응답 데이터 모양 (Pydantic) | 신청서 양식 |

`users` 도메인이 완성된 예시입니다. 새 기능은 이 도메인을 보고 같은 방식으로 작성합니다.

## 도메인끼리 의존하는 방향

```
users ◀── accounts ◀── transfers
  ▲          ▲
  └──────── cards        (체크카드 결제 → 연결 계좌 출금)
products ◀── accounts, cards   (개설·발급 시 상품 종류 검증)
```

- 다른 도메인의 데이터가 필요하면 **service에서 상대 도메인의 repository**를 호출합니다. 다른 도메인의 router는 호출하지 않습니다.
- 돈이 움직이는 처리(이체, 납입, 카드 결제)는 `async with db.begin():` 블록 **하나** 안에서 잔액 변경과 History 저장을 모두 끝냅니다.

## ERD 테이블 → 코드 위치

| ERD 테이블 | 모델 클래스 | 파일 |
|---|---|---|
| User | `User` | `domains/users/models.py` |
| Account_Products, Card_Products | `AccountProduct`, `CardProduct` | `domains/products/models.py` |
| CheckingAccount, DepositAccount, SavingsAccount | `CheckingAccount`, `DepositAccount`, `SavingsAccount` | `domains/accounts/models.py` |
| Chenking/Deposit/Savings_Account_History | `CheckingAccountHistory` 외 2개 | `domains/accounts/models.py` |
| CreditCard, DebitCard | `CreditCard`, `DebitCard` | `domains/cards/models.py` |
| Credit/Debit_Card_History | `CreditCardHistory`, `DebitCardHistory` | `domains/cards/models.py` |

> ERD의 `Chenking` 오타는 코드에서 `checking`으로 씁니다. 테이블 이름은 snake_case 복수형입니다(예: `checking_accounts`).

## 역할 분담 예시

도메인 폴더 단위로 나누면 서로 같은 파일을 고칠 일이 적습니다.

| 담당 | 폴더 |
|---|---|
| A | `products`, `users`(PATCH 추가) |
| B | `accounts` |
| C | `transfers` (`accounts` repository 사용) |
| D | `cards` (`accounts` repository 사용) |

`core/`와 `main.py`는 공용이므로 수정하기 전에 팀에 공유합니다.
