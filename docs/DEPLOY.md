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
- `/srv/avengers-bank/.env`에 `BANK_CODE=901`, `HUB_URL`, `HUB_API_KEY`, `HUB_SECRET` 추가 (등록 응답을 서버 안에서 바로 파일에 씀, 출력 안 함. 원래 파일은 `.env.bak-*`). 그다음 같은 태그로 `deploy-app avengers-bank <태그>` (`restart`로는 env가 바뀌지 않는다)
- 확인: 허브 `POST /admin/banks/901/ping` → `reachable=true, status=404 ACCOUNT_NOT_FOUND`(서명 통과, 없는 계좌), 컨테이너 안에서 `hub_client.banks()` 200(901·902), `inquiry("902","110-123-0001")` 200 김철수. 서명 없는 `POST /api/interbank/inquiry`는 401
- 키를 다시 받아야 하면: 허브 `POST /admin/banks/901/keys` → `.env`의 `HUB_API_KEY`·`HUB_SECRET` 교체 → 같은 태그로 `deploy-app`
- 다른 은행 내 계좌(SPEC 9절): `.env`에 `CI_KEY` (허브 서버 `/srv/clearing-hub/.env`의 `CI_KEY`와 같은 값, 서버 안에서 복사). 없으면 이 기능만 503
- 부인방지(Ed25519, [INTERBANK.md](INTERBANK.md)의 "부인방지(Ed25519)" 전환 순서): 키는 **서버 안에서** 만든다 `docker exec avengers-bank python -m avengers_bank.domains.interbank.keys generate`. 출력의 개인키는 `/srv/avengers-bank/.env`의 `INTERBANK_SIGNING_KEY`에만 넣고(다른 곳에 복사·저장하지 않는다, 터미널 기록은 지운다) 공개키와 지문은 허브 관리자에게 알려도 된다. `HUB_PUBLIC_KEY`는 `keys hub-key` 출력의 지문이 허브 관리자가 따로 알려 준 값과 같을 때만 넣는다. `INTERBANK_SIGNATURE_MODE`는 허브 관리자가 바꾼 우리 모드(`keys status`의 `signature_mode`)와 같게 두고, 바꿀 때마다 같은 태그로 `deploy-app`. `ed25519`인데 두 키 중 하나라도 없으면 컨테이너가 뜨지 않는다(설정 오류 로그). 개인키를 잃어버리면 새로 만들어 `register`한다. `ed25519` 모드에서는 `register`도 지금 키로 서명해야 하므로, 허브 관리자에게 모드를 `both`로 내리거나 새 공개키를 대신 등록(`POST /admin/banks/901/public-key`)해 달라고 한다. 이전 서명 증거는 옛 공개키로 계속 검증된다
- 서버 가짜 은행(SimBank 902)은 메모리 저장이라 허브를 재배포하면 입금 기록이 사라진다. 지연(`…0003`, `…0005`)은 8초
