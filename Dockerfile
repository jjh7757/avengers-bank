# 운영 이미지: React 빌드 + FastAPI를 한 컨테이너로 (avengers_bank.prod:app)
# GitHub Actions의 arm64 러너에서 빌드한다 (.github/workflows/deploy.yml). 서버에서는 빌드하지 않는다.
# 목소리 승인(voice 그룹: torch·speechbrain)은 넣지 않는다. 없으면 화자 인증만 꺼지고 버튼·PIN 승인으로 동작한다.

FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
# LightGBM이 OpenMP(libgomp)를 쓴다
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

# 의존성만 먼저 (코드가 바뀌어도 이 층은 캐시된다)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY data/seed ./data/seed
COPY data/knowledge ./data/knowledge
COPY fds_training/model ./fds_training/model
COPY scripts ./scripts
RUN uv sync --frozen --no-dev
COPY --from=frontend /frontend/dist ./frontend/dist

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
# 시작할 때마다 마이그레이션과 상품 시드(이미 있으면 건너뜀)를 적용한다. 워커 1개 (메모리 상한 512MB)
CMD ["sh", "-c", "alembic upgrade head && python scripts/seed_products.py && exec uvicorn avengers_bank.prod:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
