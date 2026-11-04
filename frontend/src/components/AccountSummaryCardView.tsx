import { Link } from 'react-router-dom'

import type { AccountSummaryCard } from '../api/types'
import { ACCOUNT_TYPE_LABEL, won } from '../lib/format'

export default function AccountSummaryCardView({ card }: { card: AccountSummaryCard }) {
  return (
    <div className="chat-card">
      <p className="chat-card-title">내 계좌</p>
      <ul className="mini-list">
        {card.accounts.map((a) => (
          <li key={`${a.account_type}-${a.account_id}`}>
            <Link to={`/accounts/${a.account_type}/${a.account_id}`}>
              {a.nickname ?? ACCOUNT_TYPE_LABEL[a.account_type]} <span className="muted small">{a.account_num}</span>
            </Link>
            <strong>{won(a.balance)}</strong>
          </li>
        ))}
      </ul>
    </div>
  )
}
