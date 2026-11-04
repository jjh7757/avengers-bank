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

```bash
docker exec avengers-bank python scripts/demo_seed.py
```

## 확인

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://avengers-bank.ai-agent-develop.cloud/api/
docker compose -f /srv/avengers-bank/docker-compose.yml ps     # 이미지 태그가 push한 커밋과 같은지
docker stats --no-stream avengers-bank                          # 메모리
```
