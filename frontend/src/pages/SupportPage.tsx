import { MessageCircle, PhoneCall, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'
import InfoPage from '../components/InfoPage'

const FAQ = [
  {
    q: '이체 PIN을 잊어버렸어요',
    a: '설정 → 이체 PIN 변경에서 로그인 비밀번호를 확인하면 새 PIN을 등록할 수 있어요.',
  },
  {
    q: 'PIN을 여러 번 틀려서 잠겼어요',
    a: '30분 동안 5번 틀리면 PIN 승인을 잠가요. 30분이 지나면 다시 시도할 수 있어요.',
  },
  {
    q: '보낸 이체를 취소하고 싶어요',
    a: '이미 보낸 이체는 앱에서 되돌릴 수 없어요. 받는 분께 돌려 달라고 요청해 주세요. 다른 은행 이체가 "확인 중"일 때 받는 은행이 거절하면 자동으로 돌려드려요.',
  },
  {
    q: '버튼을 두 번 눌렀는데 두 번 빠져나가나요?',
    a: '아니요. 이체마다 고유한 번호를 붙여 보내서, 같은 이체가 두 번 처리되지 않아요.',
  },
  {
    q: '"지난 로그인"에 모르는 시각이 있어요',
    a: '바로 비밀번호와 이체 PIN을 바꿔 주세요. 로그인 유지 토큰이 다른 곳에서 다시 쓰이면 모든 기기에서 자동으로 로그아웃돼요.',
  },
]

export default function SupportPage() {
  const { user } = useAuth()
  return (
    <InfoPage title="고객센터">
      <div className="support-alert">
        <ShieldAlert size={22} aria-hidden="true" />
        <div>
          <strong>돈을 보내라는 전화·문자를 받았나요?</strong>
          <p>
            검찰·금융기관은 전화로 이체를 요구하지 않아요. 보내지 말고 경찰(<a href="tel:112">112</a>)이나
            금융감독원(<a href="tel:1332">1332</a>)에 먼저 확인하세요.
          </p>
        </div>
      </div>

      <h2>자주 묻는 질문</h2>
      <div className="faq">
        {FAQ.map(({ q, a }) => (
          <details key={q}>
            <summary>{q}</summary>
            <p>{a}</p>
          </details>
        ))}
      </div>

      <h2>문의하기</h2>
      <div className="support-contacts">
        <Link className="list-item rich" to={user ? '/' : '/login'}>
          <span className="account-icon account-icon-checking" aria-hidden="true">
            <MessageCircle size={22} />
          </span>
          <span className="list-item-body">
            <strong>모아에게 물어보기</strong>
            <span className="muted small">약관·상품·이용 방법을 바로 알려 드려요</span>
          </span>
        </Link>
        <div className="list-item rich static">
          <span className="account-icon account-icon-savings" aria-hidden="true">
            <PhoneCall size={22} />
          </span>
          <span className="list-item-body">
            <strong>전화 상담</strong>
            <span className="muted small">시연용 서비스라 전화 상담은 운영하지 않아요</span>
          </span>
        </div>
      </div>
    </InfoPage>
  )
}
