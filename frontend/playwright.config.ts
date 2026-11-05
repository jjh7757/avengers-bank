import { defineConfig, devices } from '@playwright/test'

/**
 * E2E 테스트 (frontend/README.md "E2E 테스트").
 *
 * 테스트 전용 백엔드(SQLite 파일 e2e.db, 시연 데이터)와 Vite 개발 서버를 따로 띄운다.
 * 이미 떠 있는 개발 서버(5173·5175·8000·8001)와 겹치지 않는 포트를 쓰고, 남의 서버를 재사용하지 않는다.
 */
const API_PORT = Number(process.env.E2E_API_PORT ?? 8020)
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5180)
const API_URL = `http://127.0.0.1:${API_PORT}`
const WEB_URL = `http://localhost:${WEB_PORT}`

// 백엔드 설정. 저장소 루트의 .env보다 환경변수가 먼저라, 개발용 .env가 있어도 아래 값으로 돈다
const backendEnv = {
  DATABASE_URL: 'sqlite+aiosqlite:///./e2e.db',
  JWT_SECRET_KEY: 'e2e-secret-key-e2e-secret-key-000000',
  GEMINI_API_KEY: '', // 모아(LLM)는 부르지 않는다
  HUB_URL: '', // 타행 이체 끔: 우리 은행 안에서만 보낸다
  HUB_API_KEY: '',
  HUB_SECRET: '',
  CI_KEY: '',
  DEMO_MODE: 'false',
  SENTRY_DSN: '',
  LOG_FORMAT: 'text',
  LOG_LEVEL: 'WARNING',
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1, // 같은 시연 계정의 잔액을 쓰므로 차례로
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,
  timeout: 60_000,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: WEB_URL,
    locale: 'ko-KR',
    timezoneId: 'Asia/Seoul',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      // DB를 새로 만들고 시연 데이터를 넣은 뒤 API 서버를 띄운다 (실행할 때마다 같은 상태에서 시작)
      command: `uv run python scripts/e2e_prepare.py && uv run uvicorn avengers_bank.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: '..',
      url: `${API_URL}/health`,
      env: backendEnv,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: 'pipe',
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: WEB_URL,
      env: { API_TARGET: API_URL },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
