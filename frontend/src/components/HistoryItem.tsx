import type { AccountHistory } from '../api/types'
import { counterpartBank } from '../lib/bankNames'
import { HISTORY_TYPE_LABEL, dateTime, signedWon } from '../lib/format'

/**
 * 거래내역 한 줄. 이체면 "이체 받음/보냄" 대신 상대방 이름을 크게 보여 주고,
 * 보낸 이체는 받은 계좌(은행·계좌번호)도 함께 보여 준다.
 */
export default function HistoryItem({ h, bankName }: { h: AccountHistory; bankName: (code: string) => string }) {
  const label = HISTORY_TYPE_LABEL[h.type] ?? h.type
  const isTransfer = !!h.counterpart_account
  const title = isTransfer ? h.counterpart_name ?? h.counterpart_account : label
  const showAccount = h.type === 'TRANSFER_OUT' || h.type === 'TRANSFER_REFUND'
  return (
    <li className="list-item static history-item">
      <span>
        <strong>{title}</strong>
        {isTransfer && showAccount && (
          <span className="small history-account">
            {counterpartBank(h, bankName)} {h.counterpart_account}
          </span>
        )}
        <span className="muted small">
          {isTransfer ? `${label} · ` : ''}
          {dateTime(h.date)}
        </span>
      </span>
      <span className={`amount ${h.amount < 0 ? 'minus' : 'plus'}`}>{signedWon(h.amount)}</span>
    </li>
  )
}
