/**
 * E2E 전용 관리자 계정. playwright.config.ts가 백엔드를 띄우기 전에 관리자 CLI(create-admin)로 만든다.
 * 테스트 DB(e2e.db)에만 있는 값이다. E2E_ADMIN_PASSWORD로 바꿀 수 있다.
 */
export const ADMIN_LOGIN_ID = 'e2e-treasurer'
export const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'e2e-admin-password-0000'
