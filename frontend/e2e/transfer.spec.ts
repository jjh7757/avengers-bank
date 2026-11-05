import { expect, test, type Page } from '@playwright/test'

import { DEMO_LOGIN_ID, DEMO_PASSWORD, DEMO_PIN } from './demo-account.ts'

const AMOUNT = 10_000

/** "3,200,000원" → 3200000 */
const parseWon = (text: string) => Number(text.replace(/[^\d]/g, ''))

async function login(page: Page, password = DEMO_PASSWORD) {
  await page.goto('/login')
  await page.getByLabel('아이디').fill(DEMO_LOGIN_ID)
  await page.getByLabel('비밀번호').fill(password)
  await page.getByRole('button', { name: '로그인' }).click()
}

/** 내 계좌 화면에서 별칭으로 계좌 한 줄을 찾아 계좌번호·잔액을 읽는다 */
async function readAccount(page: Page, nickname: string) {
  const row = page.locator('.list-item', { hasText: nickname })
  await expect(row).toBeVisible()
  const accountNum = (await row.locator('.muted').innerText()).trim()
  const balance = parseWon(await row.locator('.amount').innerText())
  return { accountNum, balance }
}

test('잘못된 비밀번호로는 로그인되지 않는다', async ({ page }) => {
  await login(page, 'wrong-password-e2e')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/\/login$/)
})

test('로그인 → 계좌 → 내 다른 계좌로 1만원 이체 → 완료', async ({ page }) => {
  await login(page)
  await expect(page).not.toHaveURL(/\/login/)

  // 계좌 화면. 첫 화면(모아)은 하단 탭 없이 메뉴 버튼만 있어서 주소로 연다
  await page.goto('/accounts')
  await expect(page.getByRole('heading', { name: '내 계좌' })).toBeVisible()
  const living = await readAccount(page, '생활비')
  const salary = await readAccount(page, '월급')
  expect(living.balance).toBeGreaterThanOrEqual(AMOUNT)

  // 이체 화면: 생활비 → 월급
  await page.getByRole('link', { name: '이체하기' }).click()
  await expect(page.getByRole('heading', { name: '이체' })).toBeVisible()
  await page.getByLabel('출금 계좌').selectOption({ label: `생활비 (${living.accountNum.slice(-4)})` })
  await page.getByLabel('받는 계좌번호').fill(salary.accountNum)
  await page.getByLabel('보낼 금액').fill(String(AMOUNT))
  await page.getByRole('button', { name: '다음' }).click()

  // 받는 분 확인: 본인(홍길동) 이름이 보여야 한다
  const receipt = page.locator('.receipt')
  await expect(receipt.getByText('보낼까요?')).toBeVisible()
  await expect(receipt.getByText('홍길동').first()).toBeVisible()
  await receipt.getByRole('button', { name: '보내기' }).click()

  // FDS가 추가 인증을 요구하면(새 기기·시간대 등) 이체 PIN을 넣는다
  const pinInput = page.getByLabel('이체 PIN')
  const done = receipt.getByText('보냈어요')
  await expect(done.or(pinInput)).toBeVisible()
  if (await pinInput.isVisible()) {
    await pinInput.fill(DEMO_PIN)
    await page.getByRole('button', { name: 'PIN 확인 후 보내기' }).click()
  }

  // 완료 화면
  await expect(done).toBeVisible()
  await expect(receipt).toContainText(`${AMOUNT.toLocaleString('ko-KR')}원`)
  await expect(receipt).toContainText(`${(living.balance - AMOUNT).toLocaleString('ko-KR')}원`) // 남은 잔액

  // 계좌 화면에서 두 계좌 잔액이 바뀌었는지
  await receipt.getByRole('button', { name: '확인' }).click()
  await page.getByRole('navigation', { name: '주 메뉴' }).getByRole('link', { name: '계좌' }).click()
  await expect(page.getByRole('heading', { name: '내 계좌' })).toBeVisible()
  await expect(page.locator('.list-item', { hasText: '생활비' }).locator('.amount')).toHaveText(
    `${(living.balance - AMOUNT).toLocaleString('ko-KR')}원`,
  )
  await expect(page.locator('.list-item', { hasText: '월급' }).locator('.amount')).toHaveText(
    `${(salary.balance + AMOUNT).toLocaleString('ko-KR')}원`,
  )
})
