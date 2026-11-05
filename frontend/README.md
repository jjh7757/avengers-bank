# AvengersBank 프론트엔드

React 19 + TypeScript + Vite. 채팅형 뱅킹 화면, 이체 확인 카드, FDS 안내, 음성 입력(STT)·음성 안내(TTS).

## 실행

백엔드(`uv run fastapi dev`, 8000번)를 먼저 켭니다. 개발 서버는 `/api` 요청을 8000번으로 넘깁니다 (`vite.config.ts`).

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # 타입 검사 + 빌드
npm run lint
npm run test:e2e   # E2E (아래)
```

## E2E 테스트

[Playwright](https://playwright.dev)로 실제 브라우저에서 로그인 → 내 계좌 → 이체 화면에서 내 다른 계좌(생활비 → 월급)로 1만원 이체 → 완료 화면과 잔액 변화까지 확인합니다. 잘못된 비밀번호로 로그인이 안 되는지도 봅니다 (`e2e/transfer.spec.ts`).

```bash
npx playwright install chromium   # 처음 한 번 (브라우저 내려받기)
npm run test:e2e                  # 또는 npx playwright test
npx playwright show-report        # 결과 보기 (실패하면 스크린샷·trace가 남는다)
```

- 따로 서버를 켤 필요가 없습니다. `playwright.config.ts`가 테스트 전용 백엔드(8020번)와 Vite(5180번)를 띄우고 끝나면 끕니다. 이미 떠 있는 개발 서버(5173·8000 등)는 건드리지 않습니다. 포트는 `E2E_API_PORT`·`E2E_WEB_PORT`로 바꿀 수 있습니다.
- 백엔드는 저장소 루트의 `e2e.db`(SQLite, git 제외)를 매번 새로 만들고 `scripts/e2e_prepare.py` → `scripts/demo_seed.py`로 시연 데이터를 넣습니다. PostgreSQL·`.env`가 없어도 되고, 개발 DB는 건드리지 않습니다 (SQLite가 아니면 준비 스크립트가 멈춤).
- 로그인 비밀번호와 이체 PIN은 테스트에 적지 않고 `scripts/demo_seed.py`에서 읽습니다 (`DEMO_SEED_PASSWORD`·`DEMO_SEED_PIN` 환경변수가 있으면 그 값).
- 외부 서비스는 끕니다: 모아(Gemini), 타행 이체(ClearingHub), Sentry. FDS가 추가 인증을 요구하면 테스트가 PIN을 넣습니다.
- CI(`.github/workflows/ci.yml`의 `e2e` job)에서도 같은 설정으로 돕니다. 실패하면 리포트·trace가 artifact로 올라갑니다.

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
