#!/usr/bin/env bash
# 공용 배포 서버(deploy-server)에 avengers-bank를 처음 올릴 때 한 번 실행한다 (root, SSM Run Command 또는 Session Manager).
# - /srv/avengers-bank/docker-compose.yml (메모리 상한 512MB)
# - 공용 PostgreSQL에 role·database 생성
# - /srv/avengers-bank/.env: DB 비밀번호·JWT 키·목소리 암호화 키를 서버 안에서 생성해 바로 쓴다 (밖으로 내보내지 않는다)
# 다시 실행해도 안전하다: .env가 이미 있으면 DB·비밀값은 건드리지 않는다.
# GEMINI_API_KEY는 비워 둔다. 서버에서 직접 채운다 (docs/DEPLOY.md).
set -euo pipefail

APP=avengers-bank
DB=avengers_bank
DIR=/srv/$APP

mkdir -p "$DIR"
chown ubuntu:ubuntu "$DIR"

cat > "$DIR/docker-compose.yml" <<'EOF'
# deploy-app 스크립트가 ECR_REGISTRY / APP_NAME / IMAGE_TAG 를 넣어준다.
services:
  app:
    image: ${ECR_REGISTRY}/${APP_NAME}:${IMAGE_TAG:-latest}
    container_name: ${APP_NAME}
    restart: unless-stopped
    env_file:
      - .env
    networks:
      - web
    expose:
      - "8000"
    deploy:
      resources:
        limits:
          memory: 512M
    healthcheck:
      # 베이스 이미지(uv slim)에 wget이 없으므로 파이썬 표준 라이브러리로 확인한다
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s

networks:
  web:
    external: true
EOF
chown ubuntu:ubuntu "$DIR/docker-compose.yml"
echo "compose 작성"

if [ -f "$DIR/.env" ]; then
  echo ".env가 이미 있어 DB·비밀값은 건드리지 않음"
else
  PW="$(openssl rand -hex 24)"   # hex는 URL에 그대로 넣어도 안전하다 (base64의 / + = 문제 회피)
  docker exec -i postgres psql -U postgres -v ON_ERROR_STOP=1 -q <<SQL
CREATE ROLE $DB WITH LOGIN PASSWORD '$PW';
CREATE DATABASE $DB OWNER $DB;
SQL
  echo "PostgreSQL role·database 생성: $DB"
  umask 077
  cat > "$DIR/.env" <<EOF
DATABASE_URL=postgresql+psycopg://$DB:$PW@postgres:5432/$DB
JWT_SECRET_KEY=$(openssl rand -hex 32)
VOICE_ENCRYPTION_KEY=$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
GEMINI_API_KEY=
DEMO_MODE=false
EOF
  chown ubuntu:ubuntu "$DIR/.env"
  chmod 600 "$DIR/.env"
  echo ".env 작성 (값은 출력하지 않음)"
fi

ls -la "$DIR"
grep -o '^[A-Z_]*=' "$DIR/.env"
