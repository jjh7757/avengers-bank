# MCP 서버

은행 기능을 MCP(Model Context Protocol) 도구로 만들고, 비슷한 기능끼리 서버 5개로 묶었다. AUI 에이전트는 이 MCP 서버의 도구만 써서 은행 기능을 다룬다.

## 구조

```
React ── REST ──▶ FastAPI ─┬─ /users /accounts /transfers ... (REST API)
                           ├─ /chat ──▶ LangGraph 에이전트 ──(MCP 클라이언트, ASGI)──┐
                           └─ /mcp/{서버}/mcp  ◀───────────────────────────────────┘
                                 accounts · transfers · products · cards · security   (FastMCP, streamable HTTP)
                                         │
                                 domains/*/service.py  (REST API와 같은 규칙·트랜잭션)
```

- 서버는 같은 FastAPI 앱에 붙어 있다 (`mcp_servers/registry.py`). 앱 lifespan에서 함께 시작한다.
- 에이전트는 `langchain-mcp-adapters`의 `MultiServerMCPClient`로 붙는다. 같은 프로세스이므로 `httpx.ASGITransport`로 네트워크 없이 호출한다 (`agents/mcp_client.py`).
- 외부 MCP 클라이언트(Claude Desktop, 다른 에이전트)도 `http://127.0.0.1:8000/mcp/{서버}/mcp`에 붙을 수 있다.
- 인증: `Authorization: Bearer <JWT>` (REST 로그인 토큰과 같다). 에이전트는 대화를 처리하는 동안 그 사용자의 토큰을 새로 만들어 쓴다.
- 도구는 service를 그대로 호출하므로 본인 소유 검사, 잔액·한도, 트랜잭션 규칙이 REST API와 같다. service 오류는 `{"error": 코드, "message": ...}`로 돌려준다.
- 계좌·카드번호는 뒤 4자리만 돌려준다 (`****6789`). 예외: `prepare_transfer`의 확인 카드(앱이 이체 요청에 그대로 써야 함).
- Host 검사(DNS rebinding 방지): `127.0.0.1`, `localhost`만 허용. 배포할 때 `mcp_servers/common.py`의 `ALLOWED_HOSTS`에 실제 호스트를 더한다.

## 서버와 도구 (23개)

| 서버 | 도구 | 종류 | LLM |
|---|---|---|---|
| **accounts** 계좌 | `get_my_accounts`, `get_account`, `get_account_histories` | 조회 | ✅ |
| | `open_checking_account`, `open_deposit_account`, `open_savings_account`, `rename_account` | 변경 (사용자 동의 후) | ✅ |
| | `lower_transfer_limits` | 변경. **낮추기만** 가능 (`LIMIT_RAISE_NOT_ALLOWED`) | ✅ |
| **transfers** 이체 | `list_recipients`, `find_recipient`, `find_account_holder` | 조회 | ✅ |
| | `prepare_transfer` | 확인 카드 + 승인 토큰 (**실행 아님**) | ❌ 이체 노드만 |
| | `register_recipient`, `rename_recipient`, `delete_recipient` | 변경 | ❌ 앱 화면·외부 클라이언트만 |
| **products** 상품 | `search_products`, `get_product` | 조회 | ✅ |
| **cards** 카드 | `get_my_cards`, `get_card_histories` | 조회 | ✅ |
| | `issue_debit_card`, `issue_credit_card` | 변경 (사용자 동의 후) | ✅ |
| **security** 보안 | `get_fds_logs`, `get_voice_profile_status` | 조회 | ✅ |

## 일부러 도구로 만들지 않거나 LLM에게 주지 않은 것

| 기능 | 이유 |
|---|---|
| 이체 실행, 적금 납입·예금 입금 | 돈이 움직인다. 확인 카드 → 사용자 승인(버튼·음성·PIN) → `POST /transfers` + FDS로만 실행 |
| `prepare_transfer`를 LLM에게 | 이체 카드는 금액 재검증(정규식)과 수취인 조회를 거친 이체 노드만 만든다 |
| 수취인 등록·변경·삭제를 LLM에게 | 등록된 수취인은 FDS "처음 보내는 계좌" 검사를 건너뛴다. 붙여넣은 문자에 속아 사기 계좌를 "엄마"로 등록하는 것을 막는다 |
| 이체 한도 높이기 | 계정 탈취·보이스피싱 때 한도를 올려 빼 가는 경로. 앱 화면에서만 |
| 카드 결제 | 가맹점 쪽 기능 |
| 목소리 등록·삭제 | 녹음 파일과 비밀번호가 필요한 앱 화면 기능 |

변경 도구(계좌 개설, 카드 발급, 별칭 변경, 한도 낮추기)는 시스템 프롬프트에서 "무엇을 할지 말하고 사용자가 '네'라고 한 뒤에만 부른다"고 정했다. 실제 Gemini로 "체크카드 만들어줘" → "발급해 드릴까요?" → "네" → 발급 순서를 확인했다. 프롬프트 규칙이라 LLM이 어길 가능성은 남는다. 돈이 움직이는 도구는 이 규칙에 기대지 않고 아예 주지 않는다.

## 외부 MCP 클라이언트로 붙기

```bash
# 1. 로그인해서 JWT 받기
curl -s -X POST http://127.0.0.1:8000/users/login -H "Content-Type: application/json" -d '{"login_id":"...","password":"..."}'
```

MCP 클라이언트 설정 예 (streamable HTTP):

```json
{ "mcpServers": {
  "avengers-accounts": { "url": "http://127.0.0.1:8000/mcp/accounts/mcp", "headers": { "Authorization": "Bearer <JWT>" } }
} }
```

## 테스트

`tests/test_mcp.py`: 에이전트와 같은 방법으로 붙어서 인증, 본인 소유 검사, 번호 가리기, 한도 낮추기만 허용, 계좌 개설·카드 발급, 확인 카드 → 이체 승인, 남의 대화 거절, Host 검사를 확인한다. `tests/test_chat.py`는 LLM을 가짜로 바꾸고 MCP 도구는 실제로 부른다.
