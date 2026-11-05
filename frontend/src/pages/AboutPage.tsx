import { LogoMark } from '../components/Logo'
import InfoPage from '../components/InfoPage'

export const APP_VERSION = '1.1.0'

const LICENSES = [
  ['React, React Router', 'MIT'],
  ['Lucide 아이콘', 'ISC'],
  ['Pretendard 글꼴', 'SIL Open Font License 1.1'],
  ['FastAPI, SQLAlchemy, Pydantic', 'MIT'],
  ['LangGraph', 'MIT'],
  ['LightGBM', 'MIT'],
]

export default function AboutPage() {
  return (
    <InfoPage title="앱 정보">
      <div className="about-head">
        <LogoMark size={56} />
        <div>
          <p className="about-name">AvengersBank</p>
          <p className="muted small">버전 {APP_VERSION}</p>
        </div>
      </div>
      <p>말로 하는 은행. 도우미 모아에게 말하면 잔액 조회, 이체, 상품 가입 화면을 가져와요.</p>

      <h2>오픈소스 라이선스</h2>
      <table className="table info-table">
        <tbody>
          {LICENSES.map(([name, license]) => (
            <tr key={name}>
              <td>{name}</td>
              <td>{license}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </InfoPage>
  )
}
