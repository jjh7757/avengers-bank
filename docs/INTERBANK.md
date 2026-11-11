# 다른 은행 이체 (ClearingHub 연동)

AvengersBank는 은행 간 이체 중계 서버 [ClearingHub](https://github.com/jjh7757/clearing-hub)의 참가 은행이다. 연동 규격은 ClearingHub 저장소의 `docs/SPEC.md` (v1.0 초안). 다른 은행 서버를 직접 부르지 않고 허브만 부른다.

```
AvengersBank ──POST /v1/inquiry · /v1/transfers · GET /v1/transfers/{id}──▶ ClearingHub ──▶ 다른 은행
AvengersBank ◀──POST /interbank/inquiry · /interbank/receive · GET /interbank/receive/{id}── ClearingHub ◀── 다른 은행
```

## 동작 방식: 받기는 푸시, 결과 확인은 폴링

| 방향 | 방식 | 누가 부르나 |
|---|---|---|
| 받기 (다른 은행 → 우리) | **푸시** | 허브가 우리 `/interbank/*`를 부른다 |
| 보낸 이체의 결과 확인 | **폴링** | 우리 `worker.py`가 30초마다 허브 `GET /v1/transfers/{id}`를 부른다 (허브에는 콜백이 없음) |
| 정산 대사 | **폴링** | 우리 `worker.py`가 1시간마다 허브 `GET /v1/settlements`·`/v1/settlements/{run_id}`를 부른다 (아래 "정산 대사와 장부 정리") |

- **우리 서버는 항상 켜져 있어야 한다.** 허브가 언제 입금을 보낼지 모르기 때문이다. 별도 대기 작업은 필요 없고, 원래 떠 있는 FastAPI 서버에 `/interbank/*` 경로가 있으면 된다.
- **허브가 닿을 수 있는 주소여야 한다.** `127.0.0.1`은 외부 허브가 부를 수 없으므로, 실제로 입금을 받으려면 공인 주소에 배포하고 그 주소를 허브에 등록한다 (로컬 테스트는 허브도 로컬에 띄운다).
- **5초 안에 응답해야 한다** (허브 → 은행 타임아웃, SPEC).
- **우리 서버가 잠깐 꺼져 있어도 돈은 사라지지 않는다.** 허브는 타임아웃·`5xx`일 때 보낸 은행에 `202 PENDING`을 주고, 1분 간격으로 최대 10번 같은 `transfer_id`로 다시 보낸다 (그 전에 `GET /interbank/receive/{id}`로 이미 입금했는지 먼저 묻는다). 10번 넘게 실패하면 `UNKNOWN`이 되고 허브 관리자가 확인한다. `4xx`는 최종 거절이라 재시도하지 않는다.
- 재시도가 안전한 것은 받는 쪽이 `transfer_id`로 한 번만 입금하기 때문이다 (아래 "받기").

## 설정

허브와 주고받는 모든 요청·응답은 Ed25519로 서명한다 (SPEC v1.0 2절, 아래 "부인방지(Ed25519)"). 처음 연결하는 순서는 아래 "새 환경 설정 순서".

| 이름 | 값 |
|---|---|
| `BANK_CODE` | 허브가 배정한 우리 은행 코드 (기본 `901`, 셀프 등록 응답의 `bank_code`) |
| `HUB_URL` | 허브 주소 (`/v1` 없이) |
| `HUB_API_KEY` | 등록 때 받은 API 키. **식별용**이다 (서명 키가 아님). 셀프 등록 응답에만 나오고, 잃어버리면 허브 관리자에게 재발급을 요청한다 |
| `INTERBANK_SIGNING_KEY` | 우리 Ed25519 개인키 (`keys generate`). 허브 요청 서명과 `/interbank/*` 응답 서명에 쓴다. **허브를 포함해 누구에게도 주지 않는다** |
| `HUB_PUBLIC_KEY` | 허브 공개키. 허브 → 우리 요청과 허브 응답 서명을 검증한다. 허브 관리자가 따로 알려 준 지문과 같을 때만 넣는다 (`keys hub-key`) |
| `CI_KEY` | 가상 CI 키 (다른 은행 내 계좌, 아래). 허브 관리자가 초대 코드와 같은 개별 경로로 준다. 없으면 이 기능만 꺼진다 (`503 INTERBANK_UNAVAILABLE`) |
| `INTERBANK_SETTLEMENT_SYNC_INTERVAL_SECONDS` | 허브 정산 대사 간격 (기본 3600) |
| `INTERBANK_SETTLEMENT_SYNC_STARTUP_DELAY_SECONDS` | 시작 뒤 첫 대사까지 (기본 60). 꺼져 있던 동안 놓친 run을 이때 이어서 본다 |

넷(`HUB_URL`, `HUB_API_KEY`, `INTERBANK_SIGNING_KEY`, `HUB_PUBLIC_KEY`) 중 하나라도 없으면 타행 이체가 꺼진다: `to_bank`가 다른 은행이면 `503 INTERBANK_UNAVAILABLE`, 처리 중 확인 태스크와 정산 대사 태스크도 돌지 않는다. 일부만 넣었으면 시작 로그에 `타행 이체가 꺼져 있습니다. 비어 있는 설정: …`이 남는다. 받는 쪽 `/interbank/*`는 `INTERBANK_SIGNING_KEY`·`HUB_PUBLIC_KEY` 둘만 있으면 열린다(없으면 `503 INTERBANK_DISABLED`): 셀프 등록 직후 허브가 ping할 때는 아직 `HUB_API_KEY`가 없기 때문이다. 예전 `.env`의 `HUB_SECRET`·`INTERBANK_SIGNATURE_MODE`는 읽지 않는다 (남아 있어도 시작은 되지만 지운다).

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

**결과를 모르는 채로 되돌리지 않는다.** 되돌렸는데 받는 은행에 실제로 입금됐다면 돈이 두 배가 된다. 그래서 응답 없음은 실패가 아니라 `PENDING`이다. 그동안 돈은 아래의 **타행 송금 중간 계정**에 있다.

## 내부 계정 (중간 계정·정산 계정)

고객 계좌에서 빠진 돈과 들어온 돈이 어디서 오고 어디로 가는지 은행 내부 계정에 분개한다 (`interbank_ledger`). 고객 잔액을 바꾸는 트랜잭션 안에서 함께 쓰므로, 고객 쪽 변화와 내부 계정 변화의 합은 항상 0이다.

| 사건 | 고객 계좌 | `INTERBANK_SUSPENSE` (중간 계정) | `INTERBANK_SETTLEMENT` (상대 은행별 정산 계정) |
|---|---|---|---|
| 보내기 출금 (`debit`) | −a | +a | |
| 보내기 완료 (`_apply`) | | −a | +a (우리가 그 은행에 줄 돈) |
| 보내기 실패·되돌림 (`_refund`) | +a | −a | |
| 받기 (`receive`) | +a | | −a (그 은행이 우리에게 줄 돈) |

- **잔액 컬럼이 없다.** 잔액은 `amount`의 합이다 (`ledger_balances`). 한 행의 잔액을 갱신하면 모든 타행 이체가 그 행을 잠가 줄을 서게 되므로, 분개 행만 추가한다
- **같은 사건은 한 번만**: `(transfer_id, event, account)`가 유일하다. 재전송·확인 태스크가 겹쳐도 두 번 분개되지 않는다
- **대사** (`reconcile`, 확인 태스크가 30초마다 돈다): 중간 계정 잔액 = `PENDING` 이체 금액 합, 은행별 정산 계정 = 그 은행으로 완료된 이체 합 − 그 은행에서 받은 입금 합 + 그 은행 `SETTLE` 분개(아래 "정산 대사와 장부 정리")의 정산 계정 줄 합, 예치금 계정 = 장부를 정리한 허브 run의 `net_amount` 합. 그리고 은행마다 허브 run에 묶인 정산 계정 줄의 합은 0이어야 한다. 어긋나면 `ERROR` 로그(Sentry)를 남긴다. 거래 기록을 직접 고쳤거나 분개가 빠진 버그라는 뜻이다
- **허브 정산표와 맞춰 보기** (`settlement_positions(db, start, end)`): 기간 동안 은행별 보낸 금액·받은 금액·순액. 허브 `settlements`의 양방향 합계·순 금액과 같은 모양이다. 시각은 우리가 확정을 기록한 때라 자정 무렵 거래는 허브와 날짜가 다를 수 있다
- 기존 거래는 마이그레이션 `a8b9c0d1e2f3`이 분개로 채워 넣는다 (배포 직후부터 대사가 맞게)

**FDS**: 받는 계좌는 `902:110-123-0001`처럼 은행 코드를 붙여 넘긴다. 우리 은행의 같은 번호 계좌(등록 수취인)로 착각해 "처음 보내는 계좌" 검사를 건너뛰지 않게 하기 위해서다. 그래서 타행 계좌는 지금은 항상 처음 보내는 계좌로 본다 (수취인 등록에 은행이 없음).

**1일 한도**: 되돌려 받은 `TRANSFER_REFUND`는 오늘 보낸 금액에서 뺀다.

## 정산 대사와 장부 정리 (SPEC 10절, `settlement_sync.py`)

이체 때 은행 사이의 돈은 움직이지 않고 정산 계정에 외상으로 쌓인다. 허브는 하루치 거래를 **정산 run** 하나로 묶어 은행별 차액(받을 돈 − 줄 돈)을 계산하고(`DRAFT`), 확정하면(`SETTLED`, 참가 은행 전원 ack 또는 09:00 KST 마감) 그 차액만큼 각 은행의 **모의 예치금**을 옮긴다. 우리는 그 run의 거래 목록(대사 파일)을 우리 장부와 `transfer_id` 하나하나로 맞춰 보고, 확정된 run이 맞으면 정산 계정의 그 run 몫을 예치금 계정으로 옮긴다. 실제 금융망의 13단계 "은행 장부 정리"에 해당한다.

```
settlement_sync_loop (시작 60초 뒤 한 번, 그 뒤 1시간마다)
 1. GET /v1/settlements → 끝나지 않은 run을 run_id 작은 것부터
      끝나지 않음 = 대사 행 없음 / MATCHED가 아님 / MATCHED인데 장부를 아직 정리 안 함
      목록에서 빠진 끝나지 않은 run(취소, 30일 지남)도 상세로 다시 본다
    응답 없음·401 → 로그만, 다음 주기에 다시
 2. run마다 GET /v1/settlements/{run_id} → reconcile_run [한 트랜잭션]
      CANCELLED → 무시 (DRAFT 때 남긴 행은 지운다. 그 거래는 다음 run에 다시 나온다)
      DRAFT     → 비교하고 결과를 허브에 보낸다 (MATCHED → ack, MISMATCH → dispute. 트랜잭션 밖에서)
      SETTLED   → 비교, MATCHED면 SETTLE 분개
    확인 중(CHECKING)이면 처리 중 이체를 허브에 물어(confirm_pending) 마무리한 뒤 한 번 더 비교한다
```

**비교.** 우리 쪽 후보는 정산 계정의 `COMPLETE`(+, 허브의 `SENT`)·`RECEIVE`(−, `RECEIVED`) 줄 중 아직 어느 run에도 묶이지 않은(`hub_run_id IS NULL`) 것 전부다. 날짜로 자르지 않는다 (허브가 "미정산" 기준이라 며칠 전 거래도 들어온다).

| 허브 거래 | 판정 | `diff_json` |
|---|---|---|
| 후보에 있고 방향·금액·상대 은행이 같음 | 일치 | |
| 후보에 없지만 우리 `interbank_transfers`에서 `PENDING`, run이 `DRAFT` | 확인 중 | `checking` |
| 후보에 없지만 우리 `PENDING`, run이 `SETTLED`이고 상대 은행·금액이 같음 | **완료로 확정**하고 일치로 셈 + `WARNING` | `resolved_by_settlement` |
| 후보에 없지만 우리 `PENDING`, run이 `SETTLED`인데 상대 은행·금액이 다름 | 불일치 (확정하지 않고 `PENDING`으로 둠) | `differs` (`ours`에 `status: PENDING`) |
| 후보에 없음 (다른 run에서 이미 맞춘 거래면 `settled_in`도) | 불일치 | `hub_only` |
| 방향·금액·상대 은행이 다름 | 불일치 | `differs` (`hub`·`ours`) |
| (후보에만 있음) | 불일치가 아님. 다음 run으로 | `ours_only`. `cutoff_at − 1시간`보다 먼저 끝났으면 `ours_only_stale` + `WARNING` |

| `result` | 조건 | 장부 정리 |
|---|---|---|
| `MATCHED` | 불일치·확인 중이 없고, 일치한 거래로 계산한 순액(`our_net_amount`)이 허브 `position.net_amount`와 같음 | `SETTLED`이면 한 번 |
| `CHECKING` | 확인 중인 거래가 있음 | 안 함. 다음 주기에 다시 |
| `MISMATCH` | 불일치가 있거나 순액이 다름 (`net`) | 안 함. `ERROR` 로그와 dispute, 다음 주기에 다시 보지만 자동으로 풀리지 않는다 |

**결과를 끝내 못 받은 이체는 정산으로 확정한다.** 허브 응답이 끊겨 `PENDING`으로 남은 이체는 워커가 계속 묻지만(`confirm_pending`), 허브가 그 거래를 넣은 run을 확정(`SETTLED`)했다면 허브는 이미 그 돈을 은행 간에 옮긴 것이다. 그래서 `SETTLED` run에 우리 `PENDING` 송금이 같은 상대 은행·금액으로 들어 있으면, 그 run을 근거로 `interbank_service.complete`(중간 계정 → 정산 계정, 응답으로 완료할 때와 같은 분개)를 하고 같은 트랜잭션에서 일치로 세어 장부 정리까지 한다. 실제 은행 간 이체에서도 결과를 모르는 거래는 마감 뒤 정산 대사로 최종 확정한다. `DRAFT` run은 취소될 수 있어 근거로 쓰지 않고(확인 중), 상대 은행·금액이 다르면 확정하지 않는다(불일치). 이렇게 확정한 건은 실시간 결과를 못 받은 것이므로 `WARNING` 로그로 남겨 허브 응답 경로를 점검하게 한다. 돈을 돌려주는(환불) 쪽은 지금처럼 허브가 `FAILED`라고 할 때만 한다 (`tests/test_settlement_sync.py`의 `test_settled_run_completes_pending_transfer`, `test_settled_run_with_different_amount_keeps_pending`).

**대사 결과를 허브에 보낸다 (SPEC 10.8, 허브 정산 9단계).** 허브는 포지션이 있는 은행이 모두 ack하면 그 자리에서 확정하고, 아니면 09:00 KST에 dispute가 없으면 확정한다. 그래서 `DRAFT` run을 맞춰 본 뒤 run마다 한 번 결과를 보낸다: `MATCHED`면 `hub_client.ack_settlement(run_id)`(본문 없음), `MISMATCH`면 `hub_client.dispute_settlement(run_id, transfer_ids, message)`(`hub_only`·`differs`의 `transfer_id`, 건수 설명). 허브 관리자에게 알림이 자동으로 가므로 따로 연락하지 않는다. `CHECKING`이나 `SETTLED`에는 보내지 않는다 (`SETTLED`면 허브가 409). 보낸 결과는 `settlement_reconciliations.acked_at`·`disputed_at`에 남는데, 지금 허브에 걸려 있는 쪽만 시각이 있다 (ack를 보내면 `disputed_at`을 비운다). 그래서 결과가 바뀌면(허브 쪽이 고쳐져 `MISMATCH` → `MATCHED`) 다시 보내고, 같으면 다시 보내지 않는다. ack 응답의 `status`가 `SETTLED`(우리 ack가 마지막이었다)거나 409 `SETTLEMENT_NOT_DRAFT`(그사이 다른 은행의 ack나 마감이 확정했다)면 1시간 뒤를 기다리지 않고 상세를 다시 받아 그 자리에서 장부 정리까지 한다. 보내지 못하면(허브 응답 없음·5xx) 시각을 남기지 않아 다음 주기에 다시 보낸다. 대사 주기(기본 1시간)가 09:00 마감 전에 여러 번 돌므로, 00:05 배치의 run은 마감 전에 결과가 간다. 마감 뒤에 처음 본 run은 이미 `SETTLED`라 불일치여도 dispute를 보낼 수 없다 — 그때는 `ERROR` 로그를 보고 허브 관리자에게 직접 알린다 (마이그레이션 `d1e2f3a4b5c6`, `tests/test_settlement_sync.py`의 대사 결과 보내기 6개).

**장부 정리 (`SETTLE` 분개).** 상대 은행마다 `n` = 그 run에서 그 은행에 **줄 돈**(보낸 합 − 받은 합, 받을 돈이면 음수)에 대해 `transfer_id = "settle:{run_id}:{은행}"`으로 두 줄을 남긴다. 유니크 제약 `(transfer_id, event, account)` 때문에 같은 run을 두 번 정리할 수 없다. 맞춘 `COMPLETE`·`RECEIVE` 줄과 `SETTLE` 줄에는 `hub_run_id`를 찍는다.

| 계정 | 변화 | 뜻 |
|---|---|---|
| `INTERBANK_SETTLEMENT:{은행}` | −n | 그 은행에 줄 돈을 갚았다 (받을 돈이면 받았다) → 그 run 몫이 0이 된다 |
| `HUB_RESERVE` (`bank_code` `"000"`) | −n | 허브 예치금에서 그만큼 나갔다 (받을 돈이면 들어왔다) |

- **부호**: `HUB_RESERVE`의 변화 = Σ(−n) = 허브의 `position.net_amount`(받을 돈 − 줄 돈)다. 901 → 902 5만 원 2건, 902 → 901 3만 원 1건이면 `INTERBANK_SETTLEMENT:902` +70,000 → 0, `HUB_RESERVE` −70,000, 허브의 901 `net_amount` −70,000
- 두 줄이 같은 방향인 것은 정산 계정·중간 계정·고객 예금이 "우리가 갚을 돈"이고 `HUB_RESERVE`만 "우리가 가진 돈"이기 때문이다 (부채가 준 만큼 자산이 줄었다)
- `HUB_RESERVE`는 확정된 run의 차액 합일 뿐 허브의 실제 예치금 잔액(`GET /v1/reserve`의 `balance`)과는 다르다. 허브 관리자의 예치·인출·정정은 우리 장부에 없다
- 같은 표에 타행과 무관한 내부 계정 `CASH_VAULT`(금고 현금, `bank_code`는 우리 은행 코드)도 있다. 시연용 가상 입금(`POST /accounts/checking/{id}/cash-deposit`)마다 `CASH_DEPOSIT` 분개로 +a가 남는다 (고객 +a / 금고 +a, 둘 다 늘어나는 것은 `HUB_RESERVE`처럼 "우리가 가진 돈"이라서). `reconcile`은 `CASH_VAULT` = 고객 거래내역 `CASH_DEPOSIT` 합을 확인한다
- 주고받은 금액이 같은 은행은 옮길 돈이 없으므로 `SETTLE` 분개 없이 `hub_run_id`만 찍는다

**운영자가 `MISMATCH` 때 할 일.**

1. `settlement_reconciliations`에서 그 run의 `diff_json`을 본다 (`ERROR` 로그에도 같은 내용)
2. `hub_only`: 허브는 끝난 거래라는데 우리 장부에 없다. 받은 거래면 `interbank_receipts`, 보낸 거래면 `interbank_transfers`를 `transfer_id`로 찾는다. 입금 없이 `COMPLETED`라고 답했거나(받는 은행), 우리가 `FAILED`로 되돌렸는데 허브는 `COMPLETED`인 경우다. `settled_in`이 있으면 허브가 같은 거래를 두 run에 넣은 것이다
3. `differs`: 금액·방향·상대 은행이 다르다. 허브 관리자의 거래 기록(`GET /admin/settlements/{run_id}/transfers`)과 대조한다
4. `net`: 거래는 모두 맞는데 포지션 순액이 다르다. 허브 쪽 계산 문제이므로 허브 관리자에게 알린다
5. 허브 관리자에게 run_id와 차이 나는 `transfer_id`를 알린다. **허브는 확정된 정산을 고치지 않고** 예치금 정정(관리자 기능)으로 처리한다 (SPEC 10.6). 맞춘 뒤 그 run의 정리는 사람이 직접 한다 (자동 처리는 멈춰 있다)

`ours_only_stale` 경고는 우리 쪽에서는 끝났는데 허브 run에 계속 안 나오는 거래다 (허브가 아직 `PENDING`·`UNKNOWN`일 수 있다). 허브 관리자에게 그 `transfer_id`를 확인해 달라고 한다. 한 run이 불일치여도 이체와 다른 run의 대사는 계속된다.

## 받기: `/interbank/*` (허브 전용)

허브를 부를 때는 지금 요청의 `X-Request-ID`를 함께 보낸다 (SPEC 2.4, 서명 대상 아님). 허브가 받는 은행까지 같은 값을 넘기므로 세 서버 로그를 한 ID로 찾을 수 있다. 처리 중 확인 태스크처럼 요청 밖에서 부르면 보내지 않고 허브가 새로 만든다.

`interbank/router.py`. 허브 요청인지 `X-Bank-Code: 000` + 허브 공개키(`HUB_PUBLIC_KEY`)의 Ed25519 서명으로 확인한다. 서명에는 메서드와 경로가 들어가며(SPEC 2.2), 경로는 실제 경로(운영은 `/api/interbank/receive`)가 아니라 `/interbank` 뒤의 부분(`/receive`)으로 검증한다. 응답은 SPEC 5절 형식(`{"error", "message"}`)이다 (앱의 기본 오류 형식이 아님). 처리하지 못한 예외도 `500 {"error": "INTERNAL_ERROR"}`로 답한다(`SpecErrorRoute`, 로그·Sentry에는 남김). 허브는 5xx면 재시도하고 입금은 `transfer_id`로 멱등이다.

| 경로 | 처리 |
|---|---|
| `POST /interbank/inquiry` | 입출금 계좌번호 → 예금주 이름 / `404 ACCOUNT_NOT_FOUND` |
| `POST /interbank/receive` | 입금 + `TRANSFER_IN` 거래내역 + `interbank_receipts`를 한 트랜잭션으로. **같은 `transfer_id`는 입금하지 않고 같은 응답** (동시에 두 번 와도 기본 키 충돌로 한 번만) |
| `GET /interbank/receive/{id}` | 입금했으면 `200 COMPLETED`, 아니면 `404 TRANSFER_NOT_FOUND` (허브가 다시 보낸다) |

## 부인방지(Ed25519) (SPEC v1.0 2.3·2.5·2.6)

서명은 Ed25519 하나다 (8c·8d에서 HMAC과 서명 모드를 없앴다). 허브는 우리 비밀을 갖지 않고 공개키만 가지며, 우리도 허브 공개키만 갖는다. 개인키를 가진 쪽만 서명할 수 있으므로, 서명된 요청·응답이 있으면 보낸 사실과 답한 내용을 부인할 수 없다 (`signing.py`). 예전 HMAC secret은 허브와 나눠 가진 값이라 허브도 "AvengersBank가 보낸" 요청을 만들 수 있었다.

| 누가 | 서명하는 키 | 검증하는 키 |
|---|---|---|
| 우리 → 허브 요청 | `INTERBANK_SIGNING_KEY` | 허브에 등록된 우리 공개키 |
| 허브 → 우리 요청 (`/interbank/*`) | 허브 개인키 | `HUB_PUBLIC_KEY` |
| 우리 응답 (`/interbank/*` 2xx·4xx) | `INTERBANK_SIGNING_KEY` (`response_signing.py`) | 허브에 등록된 우리 공개키 |
| 허브 응답 (`/v1/*` 2xx·4xx) | 허브 개인키 | `HUB_PUBLIC_KEY` (`hub_client.py`) |

- 시작할 때 키 **형식**을 검사한다(`core/config.py`): 형식이 틀리면 앱이 뜨지 않는다 (서명·검증이 모두 실패해 이체가 PENDING으로 쌓이므로). 빈 값(`INTERBANK_SIGNING_KEY=`)은 없는 것으로 보고 타행 이체만 꺼진다.
- 보내는 쪽(`hub_client.py`): 늘 `X-Signature-Alg: ed25519`로 서명한다. 셀프 등록(`POST /v1/banks/register`)만 서명하지 않는다 (인증 없음, 초대 코드가 인증).
- 받는 쪽(`router.py`의 `_verified_body`): `X-Signature-Alg`가 `ed25519`이거나 없으면(없으면 ed25519, SPEC 2.1) `HUB_PUBLIC_KEY`로 검증한다. 그 밖의 값(예전 `hmac` 포함)과 헤더 없는 예전 HMAC 서명은 401 `SIGNATURE_INVALID`, 서명 헤더가 없으면 401 `UNAUTHORIZED`. 경로는 `/interbank` 뒤의 부분이다. 검증은 입금 처리보다 먼저다.
- 우리 응답 서명은 2xx·4xx(서명 검증 실패 401 포함)에 붙고 5xx에는 붙이지 않는다. `request_signature`는 허브 요청의 `X-Signature` 그대로(서명 없는 요청이면 `""`)라, 응답이 그 요청에 묶인다. **응답 서명이 없거나 틀리면 허브는 그 응답을 "응답 없음"으로 보고** 우리에게 오는 이체가 PENDING → UNKNOWN으로 쌓인다 (SPEC 2.5). 그래서 바꾼 뒤에는 꼭 `keys ping`으로 확인한다.

### 허브 응답 서명이 틀리면: "응답 없음"

허브의 2xx·4xx 응답에 응답 서명이 없거나, 틀리거나, 5분 넘게 차이 나면 `hub_client`가 그 응답을 `HubReply(None, {}, signature_valid=False)`로 바꾼다. 본문을 믿지 않는다.

| 호출 | 결과 |
|---|---|
| 이체 `POST /v1/transfers` | `200 COMPLETED`여도 완료로, `4xx`여도 거절로 보지 않는다 → **PENDING 그대로, 되돌리지 않음**. 확인 태스크가 `GET /v1/transfers/{id}`로 묻고, 서명이 맞는 응답이 오면 확정한다 |
| 결과 조회 | 모르는 상태 유지, 다음 주기에 다시 묻는다 |
| 예금주 조회·은행 목록·본인 계좌 조회 | `503 INTERBANK_UNAVAILABLE` (돈이 움직이기 전) |
| 정산 대사 | 아무것도 하지 않고 다음 주기 |
| 셀프 등록 (`keys register-bank`) | 예외: `api_key`가 그 응답에만 있어 본문은 보여 주되 경고하고 실패(1)로 끝난다. 값을 쓰기 전에 허브 관리자에게 확인한다 |

거절로 믿고 되돌렸는데 실제로 허브가 접수했다면 돈이 두 번 나간다 (SPEC 4.2·6절: 모르면 되돌리지 않는다). 대신 서명이 계속 틀리면 이체가 모두 PENDING으로 쌓이므로, 로그 `허브 응답 서명 검증 실패`가 보이면 `HUB_PUBLIC_KEY`가 지금 허브 키인지(`keys hub-key`) 확인하고 허브 관리자에게 알린다. 5xx는 서명 없이 그대로 받는다(재시도).

### 증거 (`hub_evidence`, `evidence.py`)

추가만 하고 고치거나 지우지 않는다. 본문은 서명한 바이트 그대로(`LargeBinary`), 헤더는 서명 관련만(`X-Bank-Code`, `X-Timestamp`, `X-Signature`, `X-Signature-Alg`, `X-Request-ID`, `X-Response-*`. `X-Api-Key`는 넣지 않는다).

| `direction` | 언제 | `signature_valid` |
|---|---|---|
| `TRANSFER_OUT` | 우리 → 허브 `POST /v1/transfers` (처음, 확인 중 재전송) | NULL (우리가 만든 것) |
| `TRANSFER_REPLY` | 그 요청에 대한 허브 응답 (응답을 받았을 때만) | 허브 응답 서명 검증 결과 (5xx는 NULL) |
| `RECEIVE_IN` | 허브 → 우리 `/interbank/receive`(처음·재시도)·`/interbank/receive/{id}`, **서명 검증을 통과한 것만**, 처리 전에 | True |
| `RECEIVE_REPLY` | 그 요청에 대한 우리 응답 (2xx·4xx, 응답 서명 헤더 포함) | NULL (우리가 만든 것) |

8d 이전에 남은 행은 `signature_alg`가 `hmac`이거나 `signature_valid`가 NULL일 수 있다 (그대로 둔다). 결과 조회·예금주 조회·대사 조회는 남기지 않는다. 다시 검증할 때: 요청은 `method`·`path`·`X-Timestamp`·`X-Signature`로(`verify_ed25519(..., max_skew=None)`), 응답은 `http_status`·`X-Response-*`와 바로 앞 요청 행의 `X-Signature`로(`verify_response(..., max_skew=None)`). AvengersBank에는 관리자 인증이 없어 조회 API는 만들지 않았다. DB에서 본다:

```sql
SELECT evidence_id, direction, method, path, http_status, signature_alg, signature_valid, headers_json, convert_from(body, 'UTF8')
FROM hub_evidence WHERE transfer_id = '<transfer_id>' ORDER BY evidence_id;
```

허브도 같은 거래의 접수 요청과 `/receive` 원문을 따로 보관한다 (허브 `GET /admin/transfers/{id}/evidence`). 분쟁 때 양쪽 원문을 맞대어 본다.

### 키 도구 (`keys.py`)

```
uv run python -m avengers_bank.domains.interbank.keys generate                 # 키 쌍·지문 출력 (개인키는 .env에만)
uv run python -m avengers_bank.domains.interbank.keys hub-key                  # 허브 공개키·지문 (GET /v1/hub-key)
uv run python -m avengers_bank.domains.interbank.keys register-bank --invite-code <코드> --name <이름> --base-url <주소>
                                                                               # 셀프 등록 (POST /v1/banks/register, 인증 없음)
uv run python -m avengers_bank.domains.interbank.keys ping                     # 허브가 우리 base_url을 불러 본 결과 (POST /v1/me/ping)
uv run python -m avengers_bank.domains.interbank.keys status                   # 내 등록 정보·키 상태 (GET /v1/me, GET /v1/keys)
uv run python -m avengers_bank.domains.interbank.keys register --public-key <새 공개키>   # 키 회전 (PUT /v1/keys, 지금 키로 서명)
```

- `register-bank`: `HUB_URL`·`INTERBANK_SIGNING_KEY`·`HUB_PUBLIC_KEY`가 있어야 한다(`HUB_API_KEY`는 이 응답으로 받는다). 개인키에서 공개키를 만들어 보내고 `bank_code`·`api_key`·`hub_fingerprint`·`ping`을 출력한다. 허브 응답 서명이 틀리거나, `hub_fingerprint`가 `HUB_PUBLIC_KEY`의 지문과 다르거나, `ping.ok`가 `false`면 경고하고 1로 끝난다 (등록 자체는 유지된다).
- `ping`·`status`·`register`: 이미 등록된 은행용. 넷 설정이 모두 있어야 한다. `status`는 허브에 등록된 지문·허브 지문을 우리 키와 대조해 다르면 1. `register`(인자 없음)는 지금 키의 공개키를 다시 보내는 것이라 바뀌는 것이 없다. 지금 키가 허브에 없으면 401이므로 처음 등록은 `register-bank`나 관리자 등록으로 한다.
- 배포 서버에서는 컨테이너 안에서 돌린다 (`docker exec avengers-bank python -m avengers_bank.domains.interbank.keys …`, [DEPLOY.md](DEPLOY.md)). 개인키·`api_key` 출력의 터미널 기록은 지운다.

### 새 환경 설정 순서 (SPEC 7절)

다른 팀이 이 코드를 참고하거나 AvengersBank를 새로 배포할 때. 운영의 `901`은 이미 등록돼 있으므로 이 순서를 밟지 않는다 ([DEPLOY.md](DEPLOY.md) "Ed25519 전용 전환").

| 단계 | 할 일 | 확인 |
|---|---|---|
| 1 | 허브 관리자에게 팀 이름을 알리고 **초대 코드**와 **허브 공개키 지문**을 개별 경로로 받는다 (`CI_KEY`도 필요하면 함께) | 초대 코드는 1회용, 7일 |
| 2 | `keys generate` → 서버 `.env`에 `INTERBANK_SIGNING_KEY` | 공개키·지문은 비밀이 아니다 |
| 3 | `.env`에 `HUB_URL` → `keys hub-key` → 1의 지문과 같으면 `HUB_PUBLIC_KEY` → 재배포 | `/interbank/*`가 열린다 (서명 없는 `POST /api/interbank/inquiry` → 401, 응답에 `X-Response-Signature`) |
| 4 | `keys register-bank --invite-code … --name … --base-url https://<우리 도메인>/api/interbank` | 출력의 `hub_fingerprint`가 1의 지문과 같고 `ping ok: True` |
| 5 | `.env`에 `BANK_CODE`(응답의 `bank_code`)·`HUB_API_KEY`(응답의 `api_key`) → 재배포 | 시작 로그에 "타행 이체가 꺼져 있습니다"가 없다 |
| 6 | `keys ping`, `keys status` | `ok: True`, 지문 일치 (exit 0) |
| 7 | 가짜 은행 `902`로 수취 조회·소액 이체 (SPEC 7절 6), 허브 관리자에게 받는 쪽 시험 요청 (7절 7) | 이체 `COMPLETED`, 증거 `TRANSFER_REPLY.signature_valid = true` |

- 관리자 직접 등록(`POST /admin/banks`, 코드를 정해서)이면 4 대신 공개키와 지문을 허브 관리자에게 주고 받은 `api_key`로 5를 한다.
- 키 회전: 새 키를 `generate` → `.env`는 옛 키인 채로 `keys register --public-key <새 공개키>` → 24시간 안에 `.env`를 새 개인키로 바꿔 재배포 → `keys ping`, `keys status`. 그 24시간 동안 허브는 옛 키도 받는다 (요청 서명·응답 서명 검증 모두, SPEC 2.6).
- 개인키를 잃어버렸으면 `register`를 쓸 수 없다 (옛 키로 서명해야 하므로). 새로 `generate`하고 새 공개키·지문을 허브 관리자에게 보내 대신 등록(`POST /admin/banks/{code}/public-key`)해 달라고 한다. 유출이면 바로 회전하고 허브 관리자에게 알린다. 이전 서명 증거는 옛 공개키로 계속 검증된다.

## 허브 예치금 입금·인출 신청 (SPEC v1.3 10.9, `reserve_requests.py`)

허브 예치금은 우리가 신청하고 허브 관리자가 승인해야 바뀐다. 승인을 확인하면 우리 장부도 금고 현금(`CASH_VAULT`)과
예치금(`HUB_RESERVE`) 사이에서 같은 금액을 옮긴다 (`RESERVE_MOVE` 분개 `reserve:{id}`, 한 번만). 고객 잔액은 바뀌지 않는다.

- 입금은 금고 현금 − 결정을 기다리는 입금 신청 합까지만 신청한다 (`INSUFFICIENT_VAULT_CASH`). 인출 한도(잔액 − 미정산 순채무)는 허브가 본다
- 허브에 보내기 전에 `hub_reserve_requests`에 `SENDING`으로 남긴다. 응답을 못 받으면 `confirm_loop`가 같은 `request_ref`로 다시 보낸다 (허브에서 한 건)
- `confirm_loop`가 열린(`SENDING`·`PENDING`) 신청이 있을 때만 허브에 결정을 묻는다. 승인이면 분개, 거절이면 사유를 남긴다
- `reconcile`: 예치금 = 정리한 정산 run 합 + (반영한 입금 − 인출), 금고 현금 = 가상 입금 합 − (반영한 입금 − 인출)

- 입금 신청의 "금고 잔액 검사 → `SENDING` 행 커밋"은 한 번에 하나씩만 한다 (`_deposit_guard`: PostgreSQL advisory lock + 프로세스 안 `asyncio.Lock`).
  잠그지 않으면 동시에 온 두 신청이 같은 금고 잔액을 보고 둘 다 통과한다. 잠금은 행을 커밋할 때 풀리고, 허브 호출은 잠금 밖이다

관리자 화면·API: 관리자 계정(`role = ADMIN`, 서버 CLI로만 만든다)으로 로그인하면 `/admin/treasury`(현황), `/admin/treasury/reserve-requests`(신청·목록·취소·동기화),
`/admin/audit-logs`(감사 로그)를 쓴다. 아래 CLI와 같은 함수를 부르고, 관리자 행동은 성공·실패 모두 `admin_audit_logs`에 남긴다.
경로·응답은 [API_ENDPOINTS.md](API_ENDPOINTS.md) "admin", 권한·감사 로그는 [SECURITY.md](SECURITY.md) "관리자".
실제 은행이라면 신청 전에 은행 안 결재(담당자 기안 → 책임자 승인, maker-checker)가 하나 더 있다. 여기서는 은행 신청 → 허브 관리자 승인이 이미 두 단계라 두지 않았다.

운영 도구 (서버에서는 `docker exec avengers-bank python -m …`):

```
uv run python -m avengers_bank.domains.interbank.reserve_requests deposit 5000000 --memo "11월 예치"
uv run python -m avengers_bank.domains.interbank.reserve_requests withdraw 1000000
uv run python -m avengers_bank.domains.interbank.reserve_requests list      # 최근 50건
uv run python -m avengers_bank.domains.interbank.reserve_requests sync      # 지금 결정 확인
uv run python -m avengers_bank.domains.interbank.reserve_requests cancel 3
uv run python -m avengers_bank.domains.interbank.reserve_requests reserve   # 허브의 내 예치금 GET /v1/reserve
```

## 이체 화면 (`/transfer`)

`frontend/src/pages/TransferPage.tsx`. 모아 없이 직접 보내는 화면이다. 내 계좌 → "이체하기", 입출금 계좌 상세 → "이 계좌에서 이체하기"로 들어온다.

1. 입력: 출금 계좌, 받는 은행(우리 은행 + `GET /transfers/banks`), 계좌번호, 금액(+1만·+5만·+10만·전액)
2. "다음" → `POST /transfers/inquiry`로 **받는 분 이름을 먼저 보여 준다** (다른 은행이면 허브에 물음, 돈은 안 움직임). 계좌가 없으면 입력 화면에 오류
3. "보내기" → `POST /transfers`. FDS가 PIN을 요구하면 PIN 입력, 차단하면 경고(`FdsAlert`). 결과는 완료 / "확인 중"(PENDING, 출금됐고 받는 은행 확인 중) / 되돌림(`INTERBANK_FAILED`)
4. 아래 "다른 은행 이체" 목록: 확인 중·완료·돌려받음, 새로고침

허브를 쓸 수 없으면(설정 없음·응답 없음) 받는 은행에 우리 은행만 나오고 안내 문구를 보여 준다. 화면 이체는 확인 카드(채팅)를 거치지 않고, FDS 판정(MEDIUM이면 PIN)만 적용된다 (자행 이체 화면과 같은 규칙).

로컬에서 확인: `.claude/launch.json`의 `hub-8010`(ClearingHub, `local_hub.db`), `banksim-8100`(가짜 은행), `backend-8001-hub`(허브 설정을 넣은 백엔드), `frontend-8001`. 허브 DB는 901·902를 고정 테스트 키로 등록한 시드로 만든다.

## 모아 대화

"SimBank 110-123-0001로 5만원 보내줘"도 자행 이체와 같은 확인 카드로 처리한다 (`agents/graph.py`).

1. 의도 분류기(Gemini)가 `bank_name`("SimBank")을 뽑는다. 이체 노드가 MCP `find_bank`로 은행 코드를 찾는다 (대소문자·띄어쓰기·"은행"은 무시, 우리 은행 이름이면 자행). 없으면 보낼 수 있는 은행 목록과 함께 되묻는다
2. 다른 은행은 **계좌번호로만** 보낸다 (등록 수취인·내 계좌는 우리 은행에만 있다). 번호가 없으면 금액은 기억하고 "SimBank 계좌번호를 알려 주세요". 예금주는 `find_account_holder(bank_code=...)`로 허브에 확인한다
3. `prepare_transfer(to_bank=...)` → 확인 카드에 `to_bank`, `to_bank_name`, 받는 분 "SimBank 김철수". **승인 토큰에도 은행 코드(`bk`)가 들어간다**
4. 카드 승인 → 앱이 카드의 `to_bank`를 그대로 실어 `POST /transfers`. 서버는 토큰의 은행과 요청의 은행이 다르면 `CONFIRMATION_MISMATCH` (같은 번호의 우리 은행 계좌로 바꿔치기 방지). FDS가 요구하면 PIN, 대화 위험 판별(FDS), 카드 1회 사용은 자행 이체와 같다
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
| `interbank_ledger` | 내부 계정 분개: transfer_id, account(중간·정산·예치금), bank_code(상대 은행, 예치금은 `000`), event, amount(±), 시각, hub_run_id(맞춰진 허브 정산 run) |
| `settlement_reconciliations` | 허브 정산 run별 대사 결과: hub_run_id(PK), settle_date, hub_status, hub_net_amount, our_net_amount, result(`MATCHED`/`CHECKING`/`MISMATCH`), diff_json, checked_at, settled_at(장부 정리 시각) |
| `hub_evidence` | 허브와 주고받은 이체 요청·응답 원문(부인방지 증거): transfer_id, direction(`TRANSFER_OUT`/`TRANSFER_REPLY`/`RECEIVE_IN`/`RECEIVE_REPLY`), method, path, http_status, headers_json, body(원본 바이트), signature_alg, signature_valid. 추가만 한다 |
| `own_account_lookups` | 다른 은행 내 계좌 불러오기 동의 기록: consent_id, user_id, 허브 lookup_id, 계좌 수 |
| `own_account_refs` | 허브가 준 account_ref를 사용자에게 묶음: 은행, 가린 번호, 상품명, 만료 |

거래내역 `type`에 `TRANSFER_REFUND`(타행 이체 되돌림, +)를 추가했다.

## 확인한 것

- `tests/test_nonrepudiation.py` (부인방지, Ed25519 전용): SPEC 2.3 예시 1·2와 2.5 예시 3의 고정 값(K1), 잘못된 키·서명(예전 HMAC hex 포함)은 예외 없이 실패, 변조·시각 초과, 설정 검사(형식 오류는 시작 실패, 빈 값은 없음, 넷 다 있어야 켜짐, 예전 `HUB_SECRET`·`INTERBANK_SIGNATURE_MODE`는 무시). 왕복: 우리 → 허브 Ed25519 이체 + 허브 응답 서명 검증 → `COMPLETED`, 허브 → 우리 Ed25519 `/receive`(재전송 포함)·`/receive/{id}`·`/inquiry` → 우리 응답 서명이 우리 공개키로 검증되고 그 요청에 묶임, `X-Signature-Alg` 생략은 ed25519. 예전 HMAC 허브 요청(헤더 없음·`hmac`)·모르는 방식·다른 키 → 401 `SIGNATURE_INVALID`, 서명 없음 → 401 `UNAUTHORIZED`, 모두 응답 서명 있음·입금 없음(K3·K4·K5). 허브 응답 서명이 틀림·없음 → 이체 PENDING(되돌리지 않음) → 서명 맞는 결과 조회로 `COMPLETED`, 4xx도 서명이 틀리면 되돌리지 않음, 예금주 조회는 503. 5xx 서명 없음, 운영 마운트(`/api/interbank/*`)에서도 서명, `HUB_API_KEY`만 없으면 받기만 열림. 증거 4종의 원본 바이트·`signature_valid`와 다시 검증. 키 도구 `generate`·`hub-key`·`register-bank`(서명·API 키 없이 보냄, 초대 코드 1회, 허브 서명 틀림 경고)·`ping`(허브가 실제로 우리 `/interbank/inquiry`를 불러 응답 서명 검증)·`status`·`register`(회전, 등록 안 된 키는 안내)
- 브라우저(로컬, 실제 허브·가짜 은행 서버): SimBank `0001` 5만 원 → 받는 분 "김철수" 확인 → 완료, 잔액 반영 / `0005`(입금됐는데 응답 늦음) → "확인 중" → 허브·우리 확인 태스크가 돈 뒤 새로고침하면 "완료" / `0002` → 입력 화면에 "받는 계좌를 찾을 수 없습니다", 출금 없음. 가짜 은행 입금은 건마다 1번
- 내부 계정: 시나리오마다 중간·정산 계정 잔액과 대사 확인 (완료 → 정산 +, 거절·실패 → 중간 0, PENDING → 중간 +, 재전송·재확인에도 분개 1번, 받기 → 정산 −), 양방향 상계 순액·`settlement_positions`, 거래 기록만 바꾸면 대사가 어긋남을 알림. 마이그레이션은 임시 PostgreSQL에서 기존 거래 백필 → 대사 일치 → downgrade까지 확인
- `tests/test_settlement_sync.py` (10개, SETTLEMENT_PLAN 8절 B1~B5): 맞으면 `MATCHED` → 정산 계정 0·`HUB_RESERVE` −7만·맞춘 분개에 run 표시·`reconcile` 정상, 같은 run 두 번 → 분개 한 번, 허브에만 있음·금액 다름·순액 다름 → `MISMATCH`·분개 없음, `DRAFT` → 대사만 → `SETTLED`가 되면 정리, 허브 무응답·401 → 아무것도 안 함 → 다음 주기, 우리 쪽 `PENDING` → `CHECKING` → 허브 확인 뒤 `MATCHED`, 우리에게만 있는 거래 → 다음 run에서 맞춤·오래되면 경고, 끝나지 않은 run만 run_id 순서로·취소된 DRAFT는 기록 삭제
- `tests/test_interbank.py`: 가짜 허브는 실제 허브처럼 Ed25519만 받고 응답에 서명한다. 받는 분 이름 확인(우리 은행·다른 은행·없는 계좌·없는 은행), 가짜 허브로 완료, 예금주 조회 실패 시 출금 안 함, 받는 은행 거절 → 되돌림 + 한도 복구, PENDING → 확정/실패, 허브 무응답 → PENDING 유지 → 같은 ID 재전송, 잔액 부족, 자행 코드는 자행 이체, 입금 멱등, 오류 형식, 서명 거절. 모아 대화: 카드 → 은행을 빼고 승인하면 거절 → 은행 넣어 승인 → 완료 → 재사용 거절, 계좌번호 되묻기(금액 기억), 없는 은행·없는 계좌, PENDING 승인, 대화 속 "검찰·안전계좌"가 타행 이체에도 FDS로 걸림
- 실제 ClearingHub + bank_sim 코드와 한 프로세스에서 왕복: 정상 입금, 계좌 없음, "입금됐는데 응답 없음"(`0005`) → 허브 확인 → 우리 확인 → 둘 다 `COMPLETED`·입금 1번, 반대 방향(다른 은행 → 허브 → 우리) 입금과 재전송 시 1번만 입금

## 다음 단계

- 수취인 등록에 은행 코드 (타행 수취인도 "처음 보내는 계좌" 검사를 건너뛸 수 있게)
- (완료) 배포 서버 허브 연결: [DEPLOY.md](DEPLOY.md)의 "타행 이체: ClearingHub 연결"
