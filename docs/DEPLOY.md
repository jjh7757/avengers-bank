# 배포 (AWS)

공용 배포 서버에 올린다. 환경 구성·설계 이유는 TIL 저장소의 `AWS배포환경/`(README, 새앱배포절차, DB환경구성)을 따른다.

- 주소: https://avengers-bank.ai-agent-develop.cloud
- 흐름: `feature/backend-api`에 push → GitHub Actions(arm64)가 이미지 빌드 → ECR → SSM으로 서버의 `deploy-app avengers-bank <커밋>` 실행
- 서버: EC2 `t4g.small`(2GB, 공용), `/srv/avengers-bank`, 공용 PostgreSQL(`avengers_bank` db·role), Caddy가 HTTPS
- 한 컨테이너: `avengers_bank.prod:app`이 React 빌드와 API(`/api`)를 같은 출처로 서빙 (개발 때의 Vite `/api` 프록시와 같은 경로)
- 메모리 상한 512MB (측정: 띄운 직후 약 270MB). 공용 서버라 다른 앱을 밀어내지 않게 한다
- 목소리 승인(torch·speechbrain)은 넣지 않았다. 화자 인증만 꺼지고 버튼·PIN 승인으로 동작한다

| 파일 | 역할 |
|---|---|
| `Dockerfile` | node로 프론트 빌드 → uv(Python 3.13)에 의존성(`--no-dev`) + 모델 + 시드. 시작 때 `alembic upgrade head` + 상품 시드 |
| `.github/workflows/deploy.yml` | TIL `templates/deploy.yml` 기반. 브랜치만 `feature/backend-api` |
| `src/avengers_bank/prod.py` | 운영 진입점 (`/api` + SPA, 경로 조작 차단) |
| `deploy/server-setup.sh` | 서버 최초 1회: compose, DB role·database, `.env`(비밀값을 서버 안에서 생성) |

## 처음 한 번 (완료 여부)

- [x] ECR 리포지토리 `avengers-bank` (Mutable, 최근 10개 보관)
- [x] IAM 역할 `github-actions-deploy` 신뢰 정책 `sub`에 추가: `repo:jjh7757@307797437/avengers-bank@1445025786:*`
- [x] 서버 `deploy/server-setup.sh` 실행 (SSM) → `/srv/avengers-bank/{docker-compose.yml,.env}`, PostgreSQL `avengers_bank`
- [x] 서버 `.env`에 `GEMINI_API_KEY` 채우기 (Session Manager에서 직접. 커밋하지 않는다)
- [x] 가비아 DNS: A `avengers-bank` → `13.209.128.48`, **전파 확인 후** 다음 단계
- [x] `/srv/caddy/Caddyfile`에 블록 추가 후 reload (Let's Encrypt 발급 확인)
  ```
  avengers-bank.ai-agent-develop.cloud {
      reverse_proxy avengers-bank:8000
  }
  ```
- [x] `/srv/monitor.sh`에 `check_url "avengers-bank" "https://avengers-bank.ai-agent-develop.cloud"`, `check_container_health "avengers-bank"`

## 첫 배포 (2026-11-04)

- 커밋 `b1e25eb`: Actions 전 단계 성공 → 컨테이너 `running`·`healthy`, 이미지 태그 = 커밋, 마이그레이션 6개·상품 시드 7건
- 메모리 203MB / 512MB (서버 여유 약 590MB)
- HTTPS `/`, `/accounts`(SPA), `/api/`, `/api/products/accounts` 200
- 걸린 것: 처음 Caddy reload가 적용되지 않아(validate 뒤 reload가 이어지지 않음) TLS 핸드셰이크 실패 →
  reload를 다시 실행하자 인증서 발급. reload 뒤에는 관리 API(`localhost:2019/config/`)나 로그로 실제 적용을 확인할 것

## 서버 `.env`

| 키 | 값 |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://avengers_bank:<생성>@postgres:5432/avengers_bank` |
| `JWT_SECRET_KEY` | 생성 (hex 64자) |
| `VOICE_ENCRYPTION_KEY` | 생성 (Fernet). 목소리 승인은 꺼져 있지만 설정 검증용 |
| `GEMINI_API_KEY` | 직접 입력. 없으면 대화만 503, 나머지는 동작 |
| `DEMO_MODE` | `false`. 발표 때 심야 시나리오(`/demo/clock`)가 필요하면 `true`로 바꾸고 `docker compose up -d` (로그인 없이 시각이 바뀌므로 발표 후 되돌린다) |

`.env`를 바꾸면 `restart`가 아니라 `up -d`로 컨테이너를 다시 만들어야 반영된다.

## 시연 데이터

로컬과 같은 시연 사용자(`demo`, 상대 계정 4개, 계좌·수취인·30일 거래·체크카드·이체 PIN)를 만든다. 다시 실행하면 초기화된다.

```bash
docker exec avengers-bank python scripts/demo_seed.py
```

로컬 기본 비밀번호·PIN은 저장소에 공개돼 있으므로, 서버에서는 `.env`의 `DEMO_SEED_PASSWORD`·`DEMO_SEED_PIN`을 쓴다
(서버 안에서 생성, 스크립트도 출력하지 않는다). 값 확인은 Session Manager에서:

```bash
sudo grep '^DEMO_SEED_' /srv/avengers-bank/.env
```

### 타행 연동 시험 계좌

다른 참가 은행이 AvengersBank로 시험 이체를 보낼 수 있게 ClearingHub SPEC(빠른 시작 5단계, 7절 6, 9.4)에 공개한 계좌다.
고객 `테스트수취`(로그인 불가, 생년월일 `20000101`, 휴대폰 `010-1111-2222`)의 입출금 계좌 `110-901-000001`.
없을 때만 만들고, 다시 실행해도 잔액·거래내역은 그대로다 (`demo_seed.py`와 따로라 시연 초기화에 지워지지 않는다).

```bash
docker exec avengers-bank python scripts/interbank_test_account.py
```

## 관리자 계정

자금 관리 화면(금고 현금·허브 예치금 신청)용 관리자는 회원가입으로 만들 수 없고 컨테이너 안에서 CLI로 만든다.
`-it`로 실행하면 비밀번호를 두 번 묻는다 (8자 이상, 화면·기록에 남지 않는다).

```bash
docker exec -it avengers-bank python -m avengers_bank.domains.admin.cli create-admin treasurer --name "자금 관리자" --phone 010-0000-0000
docker exec avengers-bank python -m avengers_bank.domains.admin.cli list-admins
docker exec avengers-bank python -m avengers_bank.domains.admin.cli revoke-admin treasurer   # 고객으로 강등, 바로 막힘
```

터미널 없이(스크립트) 만들 때만 `docker exec -e ADMIN_PASSWORD=… avengers-bank …`를 쓰고, 셸 기록을 지운다.
관리자 행동 기록은 `GET /api/admin/audit-logs` 또는 DB `admin_audit_logs` 표.

## 확인

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://avengers-bank.ai-agent-develop.cloud/api/
docker compose -f /srv/avengers-bank/docker-compose.yml ps     # 이미지 태그가 push한 커밋과 같은지
docker stats --no-stream avengers-bank                          # 메모리
```

## 타행 이체: ClearingHub 연결 (2026-11-05)

같은 서버의 [ClearingHub](https://github.com/jjh7757/clearing-hub)(`clearing-hub.ai-agent-develop.cloud`)에 참가 은행 901로 등록했다. 자세한 동작은 [INTERBANK.md](INTERBANK.md).

- 허브 → 우리: `base_url = http://avengers-bank:8000/api/interbank` (같은 서버의 `web` 네트워크 안)
- 우리 → 허브: `HUB_URL = https://clearing-hub.ai-agent-develop.cloud`
- `/srv/avengers-bank/.env`에 `BANK_CODE=901`, `HUB_URL`, `HUB_API_KEY` (등록 응답을 서버 안에서 바로 파일에 씀, 출력 안 함. 원래 파일은 `.env.bak-*`). 8d부터 `INTERBANK_SIGNING_KEY`·`HUB_PUBLIC_KEY`도 필요하다 (아래 "Ed25519 전용 전환"). `.env`를 바꾸면 같은 태그로 `deploy-app avengers-bank <태그>` (`restart`로는 env가 바뀌지 않는다)
- 확인: `docker exec avengers-bank python -m avengers_bank.domains.interbank.keys ping` → `ok: True`(허브가 우리 `/api/interbank/inquiry`를 허브 키로 불러 404 `ACCOUNT_NOT_FOUND` + 우리 응답 서명 확인), `keys status` → 지문 일치. 허브 쪽에서는 `POST /admin/banks/901/ping`이 같은 결과. 서명 없는 `POST /api/interbank/inquiry`는 401 (응답에 `X-Response-Signature`)
- API 키를 다시 받아야 하면: 허브 `POST /admin/banks/901/keys` → `.env`의 `HUB_API_KEY` 교체 → 같은 태그로 `deploy-app`
- 다른 은행 내 계좌(SPEC 9절): `.env`에 `CI_KEY` (허브 서버 `/srv/clearing-hub/.env`의 `CI_KEY`와 같은 값, 서버 안에서 복사). 없으면 이 기능만 503
- 키 관리([INTERBANK.md](INTERBANK.md) "키 도구"): 도구는 **컨테이너 안에서** 돌린다 `docker exec avengers-bank python -m avengers_bank.domains.interbank.keys <명령>`. 개인키(`generate`)와 `api_key`(`register-bank`) 출력은 `.env`에만 옮기고 다른 곳에 복사·저장하지 않는다 (터미널 기록은 지운다). 공개키와 지문은 허브 관리자에게 알려도 된다. 회전은 `keys register --public-key <새 공개키>` 뒤 24시간 안에 `.env`를 새 개인키로 바꿔 `deploy-app`. 개인키를 잃어버리면 새로 만들어 허브 관리자에게 새 공개키를 대신 등록(`POST /admin/banks/901/public-key`)해 달라고 한다. 이전 서명 증거는 옛 공개키로 계속 검증된다
- 서버 가짜 은행(SimBank 902)은 메모리 저장이라 허브를 재배포하면 입금 기록이 사라진다. 지연(`…0003`, `…0005`)은 8초

### Ed25519 전용 전환 (8d, 허브 8c와 함께)

허브 8c(SPEC v1.0)부터 허브는 Ed25519 서명만 받고 보내며, AvengersBank 8d도 Ed25519만 쓴다(`HUB_SECRET`·`INTERBANK_SIGNATURE_MODE` 삭제). 둘은 **같은 때** 배포한다. 허브 쪽 순서는 ClearingHub `docs/DEPLOY.md` "Ed25519 필수화 배포 순서"이고, 그 1번(901 공개키 등록)이 먼저다.

1. **키 만들기 (배포 전, 서버 안에서).** 지금 이미지에 `keys` 도구가 있으면(8b 이후) `docker exec avengers-bank python -m avengers_bank.domains.interbank.keys generate`, 없으면 허브와 같이 `openssl`로 만든다 (raw 32바이트 = PKCS#8 DER의 끝 32바이트):
   ```bash
   sudo grep -q '^INTERBANK_SIGNING_KEY=.\+' /srv/avengers-bank/.env || \
     echo "INTERBANK_SIGNING_KEY=$(openssl genpkey -algorithm ed25519 -outform DER | tail -c 32 | base64)" | sudo tee -a /srv/avengers-bank/.env >/dev/null
   ```
   공개키와 지문은 배포 전에 허브 관리자에게 줘야 하므로 개인키에서 바로 만든다 (개인키는 화면에 내지 않는다. `keys generate`로 만들었으면 그 출력의 공개키·지문을 쓴다):
   ```bash
   KEY=$(sudo grep '^INTERBANK_SIGNING_KEY=' /srv/avengers-bank/.env | cut -d= -f2)
   PUB=$( (printf '\x30\x2e\x02\x01\x00\x30\x05\x06\x03\x2b\x65\x70\x04\x22\x04\x20'; echo "$KEY" | base64 -d) \
         | openssl pkey -inform DER -pubout -outform DER | tail -c 32 | base64)
   echo "공개키 $PUB  지문 $(echo "$PUB" | base64 -d | sha256sum | cut -c1-16)"; unset KEY
   ```
2. **허브 관리자와 주고받기 (개별 경로).** 우리 → 관리자: 공개키·지문 (관리자가 `POST /admin/banks/901/public-key`로 등록하고, 응답의 `public_key_fingerprint`가 우리 지문과 같은지 본다). 관리자 → 우리: 허브 공개키와 그 지문. 허브 공개키를 `.env`의 `HUB_PUBLIC_KEY`에 넣기 전에 지문을 맞춘다 `echo "$HUB_PUB" | base64 -d | sha256sum | cut -c1-16`. 허브 8c 배포 뒤에는 `keys hub-key`의 지문과도 같아야 한다
3. **`.env` 정리.** `INTERBANK_SIGNING_KEY`, `HUB_PUBLIC_KEY`가 있고 `HUB_SECRET`·`INTERBANK_SIGNATURE_MODE` 줄은 지운다 (남아 있어도 무시되지만 헷갈린다). 아직 재배포하지 않는다: 8d 전 이미지에서 `INTERBANK_SIGNATURE_MODE`가 없으면 `hmac`이라 지금 동작은 그대로다
4. **배포.** 허브 8c 배포(1번 공개키 등록이 배포 전에 안 됐으면 배포 직후 가장 먼저) → 바로 AvengersBank 8d 이미지로 `deploy-app avengers-bank <태그>`. 둘 사이에는 901의 허브 요청이 401이고, 901로 오는 이체는 허브가 접수 전에 거절하거나(공개키 없음) 우리가 401로 거절해 `FAILED`로 끝난다. 우리가 보낸 이체는 서명 없는 401을 받으면 PENDING으로 남는다. 이중 지급은 없지만 시연·실사용이 없는 시간에 짧게 붙여서 한다
5. **확인.** `keys ping` → `ok: True`, `keys status` → exit 0(지문 일치), 시작 로그에 "타행 이체가 꺼져 있습니다"가 없다. 허브 관리자 `POST /admin/banks/901/ping`도 `ok: true`. 모아 화면에서 902로 소액 이체 → `COMPLETED`, DB `hub_evidence`의 그 거래 `TRANSFER_REPLY.signature_valid = true`

되돌리기는 허브와 함께만 할 수 있다 (한쪽만 되돌리면 서로의 서명을 받지 않는다). 허브 8c 마이그레이션이 `hmac_secret`을 지우므로 옛 `HUB_SECRET`으로 그냥 돌아갈 수는 없다. 문제가 생기면 되돌리기보다 `keys ping`·`keys status`로 키를 맞춘다.
