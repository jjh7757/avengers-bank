# ER 다이어그램

- 원본 파일: [`AvengersBankDiagram.drawio`](AvengersBankDiagram.drawio). [draw.io](https://app.diagrams.net)에서 열어서 수정합니다.
- 아래 다이어그램은 같은 내용을 GitHub에서 바로 볼 수 있도록 Mermaid로 옮긴 것입니다. drawio를 수정하면 이 문서도 함께 고쳐 주세요.
- 코드의 모델은 `src/avengers_bank/domains/*/models.py`에 있습니다.

```mermaid
erDiagram
    users {
        int user_id PK
        string login_id UK
        string hashed_password
        string name
        string nick_name "NULL"
        string phone
        datetime created_at
    }

    account_products {
        int product_id PK
        string type "CHECKING/DEPOSIT/SAVINGS"
        string name
        text description
        decimal interest_rate "연 금리(%)"
    }

    card_products {
        int product_id PK
        string type "CREDIT/DEBIT"
        string name
        text description
    }

    checking_accounts {
        int checking_account_id PK
        int user_id FK
        int product_id FK
        string account_num UK
        bigint balance
        bigint per_transfer_limit "1회 이체 한도"
        bigint daily_transfer_limit "1일 이체 한도"
        string nickname "NULL"
        datetime created_at
    }

    deposit_accounts {
        int deposit_account_id PK
        int user_id FK
        int product_id FK
        string account_num UK
        bigint balance
        date maturity_date
        string nickname "NULL"
        datetime created_at
    }

    savings_accounts {
        int savings_account_id PK
        int user_id FK
        int product_id FK
        string account_num UK
        bigint balance
        bigint monthly_payment
        smallint monthly_deposit_date "매월 납입일 1~31"
        date maturity_date
        string nickname "NULL"
        datetime created_at
    }

    checking_account_histories {
        int checking_account_history_id PK
        int checking_account_id FK
        datetime date
        bigint change_amount
        string type
        string from_account "NULL"
        string sending_account "NULL"
    }

    deposit_account_histories {
        int deposit_account_history_id PK
        int deposit_account_id FK
        datetime date
        bigint deposit_amount
        string type
        string from_account "NULL"
    }

    savings_account_histories {
        int savings_account_history_id PK
        int savings_account_id FK
        datetime date
        bigint deposit_amount
        string type
        string from_account "NULL"
    }

    credit_cards {
        int credit_card_id PK
        int user_id FK
        int product_id FK
        int checking_account_id FK "결제 계좌"
        string card_num UK
        bigint accumulated_amount
        smallint payment_date "매월 결제일 1~31"
    }

    debit_cards {
        int debit_card_id PK
        int user_id FK
        int product_id FK
        int checking_account_id FK "출금 계좌"
        string card_num UK
        bigint accumulated_amount
    }

    credit_card_histories {
        int credit_card_history_id PK
        int credit_card_id FK
        string place_of_use
        bigint used_amount
        datetime time
    }

    debit_card_histories {
        int debit_card_history_id PK
        int debit_card_id FK
        string place_of_use
        bigint used_amount
        datetime time
    }

    users ||--o{ checking_accounts : "보유"
    users ||--o{ deposit_accounts : "보유"
    users ||--o{ savings_accounts : "보유"
    users ||--o{ credit_cards : "보유"
    users ||--o{ debit_cards : "보유"

    account_products ||--o{ checking_accounts : "상품"
    account_products ||--o{ deposit_accounts : "상품"
    account_products ||--o{ savings_accounts : "상품"
    card_products ||--o{ credit_cards : "상품"
    card_products ||--o{ debit_cards : "상품"

    checking_accounts ||--o{ checking_account_histories : "거래"
    deposit_accounts ||--o{ deposit_account_histories : "거래"
    savings_accounts ||--o{ savings_account_histories : "거래"

    checking_accounts ||--o{ credit_cards : "결제 계좌"
    checking_accounts ||--o{ debit_cards : "출금 계좌"

    credit_cards ||--o{ credit_card_histories : "사용"
    debit_cards ||--o{ debit_card_histories : "사용"
```

## 테이블 요약

| 테이블 | 설명 | 도메인 |
|---|---|---|
| `users` | 회원 | users |
| `account_products` / `card_products` | 계좌 상품 / 카드 상품 | products |
| `checking_accounts` / `deposit_accounts` / `savings_accounts` | 입출금 / 예금 / 적금 계좌 | accounts |
| `*_account_histories` | 계좌별 거래내역 | accounts |
| `credit_cards` / `debit_cards` | 신용카드 / 체크카드 | cards |
| `*_card_histories` | 카드별 사용내역 | cards |

## 코드에서 지켜야 할 규칙

DB 구조만으로는 막을 수 없는 부분이라 애플리케이션 코드에서 보장해야 합니다.

1. **계좌번호 중복 방지:** 계좌 테이블이 3개라서 `account_num`이 테이블 사이에서 겹칠 수 있습니다. 계좌번호는 `accounts.service`에서만 발급하고, 세 테이블을 모두 검사합니다.
2. **돈 이동은 한 트랜잭션으로:** 이체, 적금 납입, 체크카드 결제는 잔액 변경과 History 저장(양쪽 모두)을 `async with db.begin():` 블록 하나 안에서 처리합니다.
3. **상품 종류 검증:** 계좌를 개설하거나 카드를 발급할 때 상품의 `type`이 계좌·카드 종류와 맞는지 확인합니다.
4. **`accumulated_amount` 동기화:** 카드 History를 저장할 때 이 값도 같이 증가시킵니다.
5. **금액은 정수(원):** 금액 컬럼은 모두 `BIGINT`입니다. 실수형(`float`)은 쓰지 않습니다.

## 팀에서 정해야 할 것

- 각 `type` 컬럼에 들어갈 값 목록 (예: 거래내역 `DEPOSIT`, `WITHDRAW`, `TRANSFER_IN`, `TRANSFER_OUT`, `CARD_PAYMENT`)
- 계좌번호와 카드번호를 만드는 형식
- 이체 한도 기본값
