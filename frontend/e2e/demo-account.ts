import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

/**
 * 시연 계정(scripts/demo_seed.py가 만드는 demo)의 비밀번호·이체 PIN.
 * 값을 테스트 코드에 다시 적지 않고 시드 스크립트에서 읽는다. 시드처럼 DEMO_SEED_PASSWORD·DEMO_SEED_PIN 환경변수가 먼저다.
 */
const SEED = fileURLToPath(new URL('../../scripts/demo_seed.py', import.meta.url))

function seedDefault(name: string): string {
  const source = readFileSync(SEED, 'utf-8')
  // 예: PASSWORD = os.environ.get("DEMO_SEED_PASSWORD") or "..."
  const match = source.match(new RegExp(`^${name}\\s*=\\s*os\\.environ\\.get\\("[A-Z_]+"\\)\\s*or\\s*"([^"]+)"`, 'm'))
  if (!match) throw new Error(`scripts/demo_seed.py에서 ${name} 기본값을 찾지 못했습니다`)
  return match[1]
}

export const DEMO_LOGIN_ID = 'demo'
export const DEMO_PASSWORD = process.env.DEMO_SEED_PASSWORD || seedDefault('PASSWORD')
export const DEMO_PIN = process.env.DEMO_SEED_PIN || seedDefault('PIN')
