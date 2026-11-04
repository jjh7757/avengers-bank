# AvengersBank 프론트엔드

React 19 + TypeScript + Vite. 채팅형 뱅킹 화면, 이체 확인 카드, FDS 안내, 음성 입력(STT)·음성 안내(TTS).

## 실행

백엔드(`uv run fastapi dev`, 8000번)를 먼저 켭니다. 개발 서버는 `/api` 요청을 8000번으로 넘깁니다 (`vite.config.ts`).

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # 타입 검사 + 빌드
npm run lint
```

음성 입력은 Chrome·Edge에서만 동작합니다 (Web Speech API). 마이크 권한을 허용해야 합니다.

## 화면

| 경로 | 화면 |
|---|---|
| `/login`, `/signup` | 로그인·회원가입 |
| `/` | 채팅 홈: 에이전트 대화, 이체 확인 카드, 계좌 요약 카드, FDS 안내 |
| `/accounts`, `/accounts/:type/:id` | 내 계좌, 거래내역 |
| `/cards`, `/cards/:type/:id` | 내 카드, 사용내역 |
| `/settings` | 내 정보, 이체 PIN 등록, 로그아웃 |
| `/fds` | 이상거래 탐지 기록 (발표용) |

## 폴더

```
src/
├── api/          client.ts(fetch·JWT·오류), endpoints.ts(API 함수), types.ts(응답 타입)
├── auth/         AuthProvider(로그인 상태), useAuth
├── components/   Layout(하단 탭), TransferCard(확인 카드·PIN·차단), FdsAlert, AccountSummaryCardView
├── hooks/        useSpeech(STT·TTS), useLoad(화면 데이터 불러오기)
├── lib/          format(금액·날짜), fingerprint(기기 식별값)
└── pages/
```

## 음성 흐름 (PROJECT_PLAN.md 3.5)

1. 마이크 버튼을 누르고 있는 동안 듣고, 손을 떼면 인식 결과를 입력창에 보여 준다.
2. TTS로 "○○, 라고 말씀하셨나요? 맞으면 확인이라고 말씀해 주세요"라고 묻고 5초 동안 대답을 듣는다.
3. "확인" → 전송, "아니"·"취소" → 버리고 다시 듣기, 대답 없음 → 입력창에 남김.
4. 에이전트 답변은 TTS로 읽는다 (기본 켜짐). 확인 카드는 `tts_text`만 읽고 계좌번호는 읽지 않는다.
5. FDS 추가 인증·차단 안내는 음성 안내를 꺼 두어도 읽는다.
6. 마이크 버튼을 누르면 읽던 안내는 멈춘다.
