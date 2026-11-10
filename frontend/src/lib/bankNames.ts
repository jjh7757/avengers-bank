import { useEffect, useState } from 'react'

import { transferApi } from '../api/endpoints'
import type { AccountHistory } from '../api/types'

export const OWN_BANK_NAME = 'AvengersBank'

// 다른 은행 이름은 허브 목록에서 찾는다. 화면마다 다시 묻지 않도록 한 번만 불러 둔다 (실패하면 코드 그대로)
let bankNames: Promise<Record<string, string>> | null = null
function loadBankNames() {
  bankNames ??= transferApi.banks().then(
    (list) => Object.fromEntries(list.map((b) => [b.bank_code, b.name])),
    () => {
      bankNames = null // 허브가 잠깐 안 되면 다음 화면에서 다시 묻는다
      return {}
    },
  )
  return bankNames
}

/** 다른 은행 코드 → 이름. 이름을 모르는 다른 은행 이체가 있을 때만 허브 목록을 부른다 */
export function useBankNames(histories: AccountHistory[] | null | undefined) {
  const [names, setNames] = useState<Record<string, string>>({})
  const needed = (histories ?? []).some((h) => h.counterpart_bank && !h.counterpart_bank_name)
  useEffect(() => {
    if (!needed) return
    let alive = true
    loadBankNames().then((n) => alive && setNames(n))
    return () => {
      alive = false
    }
  }, [needed])
  return (code: string) => names[code] ?? code
}

/** 상대 은행 이름: 우리 은행이면 AvengersBank, 받은 이체는 허브가 알려 준 이름, 아니면 목록에서 */
export function counterpartBank(h: AccountHistory, bankName: (code: string) => string) {
  if (!h.counterpart_bank) return OWN_BANK_NAME
  return h.counterpart_bank_name ?? bankName(h.counterpart_bank)
}
