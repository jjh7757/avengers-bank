import { expect, test, type Page } from '@playwright/test'

import { ADMIN_LOGIN_ID, ADMIN_PASSWORD } from './admin-account.ts'
import { DEMO_LOGIN_ID, DEMO_PASSWORD } from './demo-account.ts'

async function login(page: Page, loginId: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('아이디').fill(loginId)
  await page.getByLabel('비밀번호').fill(password)
  await page.getByRole('button', { name: '로그인' }).click()
}

const mainNav = (page: Page) => page.getByRole('navigation', { name: '주 메뉴' })

test('관리자는 로그인하면 자금 관리 화면으로 간다', async ({ page }) => {
  await login(page, ADMIN_LOGIN_ID, ADMIN_PASSWORD)

  await expect(page).toHaveURL(/\/admin\/treasury$/)
  await expect(page.getByRole('heading', { name: '자금 관리' })).toBeVisible()
  await expect(mainNav(page).getByRole('link', { name: '자금 관리' })).toBeVisible()
  await expect(mainNav(page).getByRole('link', { name: '계좌' })).toHaveCount(0)

  // 현황: 금고 현금 카드, 예치금은 장부 값과 허브 값. E2E 백엔드는 허브 설정이 없어(HUB_URL='') 허브 값이 없다
  await expect(page.getByText('금고 현금', { exact: true })).toBeVisible()
  await expect(page.getByText('우리 장부')).toBeVisible()
  await expect(page.getByText('허브 값 없음')).toBeVisible()
  await expect(page.getByText(/허브 연결 설정이 없어요/)).toBeVisible()
  await expect(page.getByText(/장부 일치|장부 대사 불일치/)).toBeVisible()

  // 신청 폼·내역·감사 로그 영역
  await expect(page.getByRole('radiogroup', { name: '신청 종류' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '신청 내역' })).toBeVisible()
  await expect(page.getByRole('button', { name: '허브와 동기화' })).toBeDisabled() // 허브 설정 없음
  await expect(page.getByRole('heading', { name: '감사 로그' })).toBeVisible()
})

test('고객에게는 자금 관리 메뉴가 없고, 주소로 들어가도 막힌다', async ({ page }) => {
  await login(page, DEMO_LOGIN_ID, DEMO_PASSWORD)
  await expect(page).not.toHaveURL(/\/login/)

  await page.goto('/accounts')
  await expect(page.getByRole('heading', { name: '내 계좌' })).toBeVisible()
  await expect(mainNav(page).getByRole('link', { name: '계좌' })).toBeVisible()
  await expect(mainNav(page).getByRole('link', { name: '자금 관리' })).toHaveCount(0)

  await page.goto('/admin/treasury')
  await expect(page.getByText('관리자만 쓸 수 있는 화면이에요')).toBeVisible()
  await expect(page.getByRole('heading', { name: '자금 관리' })).toHaveCount(0)
})
