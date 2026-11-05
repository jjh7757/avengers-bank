"""다른 은행 이체 (ClearingHub 연동). 허브는 이 파일의 가짜 허브(SPEC 3절)로 대신한다.

가짜 허브의 받는 계좌번호 끝 4자리:
  0001 완료 · 0002 조회부터 계좌 없음 · 0003 202 PENDING(나중에 허브 결과가 바뀜)
  0006 허브가 응답 안 함(요청도 저장 안 함) · 0007 조회는 되는데 이체에서 받는 은행이 거절
"""

import asyncio
import json
import os

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank.hub_client import hub_client
from avengers_bank.domains.interbank.service import confirm_pending
from avengers_bank.domains.interbank.signing import sign, verify
from tests.conftest import new_chat_session, open_checking
from tests.test_chat import approve, classify, say  # noqa: F401  classify는 fixture

pytestmark = pytest.mark.anyio
SECRET = os.environ["HUB_SECRET"]


class FakeHub:
    def __init__(self):
        self.app = FastAPI()
        self.transfers: dict[str, dict] = {}  # 허브가 저장한 거래
        self.transfer_calls: list[dict] = []
        self.hub_down = False
        self.request_ids: list[tuple[str, str | None]] = []  # (경로, 받은 X-Request-ID)
        self._routes()

    def _routes(self):
        app = self.app

        async def check(request: Request) -> bytes | JSONResponse:
            self.request_ids.append((request.url.path, request.headers.get("x-request-id")))
            body = await request.body()
            ok = (request.headers.get("x-bank-code") == "901" and request.headers.get("x-api-key") == "chk_test_api_key"
                  and verify(SECRET, request.headers.get("x-timestamp"), body, request.headers.get("x-signature")) is None)
            return body if ok else JSONResponse(status_code=401, content={"error": "SIGNATURE_INVALID", "message": "서명"})

        @app.get("/v1/banks")
        async def banks(request: Request):
            if isinstance(r := await check(request), JSONResponse):
                return r
            return {"banks": [{"bank_code": "901", "name": "AvengersBank"}, {"bank_code": "902", "name": "SimBank"}]}

        @app.post("/v1/inquiry")
        async def inquiry(request: Request):
            if isinstance(body := await check(request), JSONResponse):
                return body
            data = json.loads(body)
            if data["to_account"].endswith("0002"):
                return JSONResponse(status_code=404, content={"error": "ACCOUNT_NOT_FOUND", "message": "받는 계좌를 찾을 수 없습니다"})
            return {**data, "holder_name": "김철수"}

        @app.post("/v1/transfers")
        async def transfer(request: Request):
            if isinstance(body := await check(request), JSONResponse):
                return body
            data = json.loads(body)
            self.transfer_calls.append(data)
            tid = data["transfer_id"]
            if tid in self.transfers:  # 멱등
                return self._result(self.transfers[tid])
            suffix = data.get("to_account", "")[-4:]  # 참조값(to_account_ref)으로 오면 계좌번호가 없다 → 완료
            if suffix == "0006" and self.hub_down:
                await asyncio.sleep(1)  # 우리 타임아웃(0.3초)보다 길게, 저장도 안 함
                return {}
            status = {"0003": "PENDING", "0007": "FAILED"}.get(suffix, "COMPLETED")
            self.transfers[tid] = {**data, "status": status}
            return self._result(self.transfers[tid])

        @app.get("/v1/transfers/{tid}")
        async def get_transfer(tid: str, request: Request):
            if isinstance(r := await check(request), JSONResponse):
                return r
            if tid not in self.transfers:
                return JSONResponse(status_code=404, content={"error": "TRANSFER_NOT_FOUND", "message": "없음"})
            t = self.transfers[tid]
            return {"transfer_id": tid, "status": t["status"], "fail_code": t.get("fail_code"),
                    "fail_message": t.get("fail_message")}

    def _result(self, t: dict) -> JSONResponse:
        if t["status"] == "FAILED":
            return JSONResponse(status_code=404, content={"error": "ACCOUNT_NOT_FOUND", "message": "받는 계좌를 찾을 수 없습니다",
                                                          "transfer_id": t["transfer_id"], "status": "FAILED"})
        code = 200 if t["status"] == "COMPLETED" else 202
        return JSONResponse(status_code=code, content={"transfer_id": t["transfer_id"], "status": t["status"], "holder_name": "김철수"})


@pytest.fixture
async def hub(client, monkeypatch):
    fake = FakeHub()
    http = AsyncClient(transport=ASGITransport(app=fake.app), base_url="http://hub")
    monkeypatch.setattr(hub_client, "_client", http)
    yield fake
    await http.aclose()


async def send(client, headers, account_id: int, to_account: str, amount: int = 30_000, **extra):
    return await client.post("/transfers", headers=headers, json={
        "from_checking_account_id": account_id, "to_bank": "902", "to_account_num": to_account, "amount": amount, **extra,
    })


async def balance_of(client, headers, account_id: int) -> int:
    return (await client.get(f"/accounts/checking/{account_id}", headers=headers)).json()["data"]["balance"]


async def history_types(client, headers, account_id: int) -> list[tuple[str, int]]:
    rows = (await client.get(f"/accounts/checking/{account_id}/histories", headers=headers)).json()["data"]
    return sorted((h["type"], h["amount"]) for h in rows)


async def interbank_list(client, headers) -> list[dict]:
    return (await client.get("/transfers/interbank", headers=headers)).json()["data"]


# ── 보내기 ──────────────────────────────────────────────────────

async def test_banks_excludes_own(client, user, hub):
    res = await client.get("/transfers/banks", headers=user)
    assert res.json()["data"] == [{"bank_code": "902", "name": "SimBank"}]


async def test_send_completed(client, user, hub):
    source = await open_checking(client, user, balance=100_000)
    res = await send(client, user, source["account_id"], "110-123-0001")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert (data["status"], data["to_bank"], data["to_holder_name"], data["balance_after"]) == ("COMPLETED", "902", "김철수", 70_000)

    [call] = hub.transfer_calls
    assert call["transfer_id"] == data["transfer_id"]
    assert (call["from_account"], call["amount"], call["sender_name"]) == (source["account_num"], 30_000, "토니 스타크")
    assert await history_types(client, user, source["account_id"]) == [("TRANSFER_OUT", -30_000)]
    assert (await interbank_list(client, user))[0]["status"] == "COMPLETED"


async def test_request_id_passed_to_hub(client, user, hub):
    """앱이 보낸 X-Request-ID가 예금주 조회·이체 요청에 그대로 실려 허브로 간다 (SPEC 2.4)"""
    source = await open_checking(client, user, balance=100_000)
    traced = {**user, "X-Request-ID": "app-trace-0001"}
    res = await send(client, traced, source["account_id"], "110-123-0001")
    assert res.status_code == 200, res.text
    assert res.headers["x-request-id"] == "app-trace-0001"
    sent = [rid for path, rid in hub.request_ids if path in ("/v1/inquiry", "/v1/transfers")]
    assert sent and set(sent) == {"app-trace-0001"}


async def test_send_account_not_found_before_debit(client, user, hub):
    source = await open_checking(client, user, balance=100_000)
    res = await send(client, user, source["account_id"], "110-123-0002")
    assert res.status_code == 404 and res.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    assert hub.transfer_calls == []
    assert await balance_of(client, user, source["account_id"]) == 100_000


async def test_send_rejected_by_receiver_refunds(client, user, hub):
    source = await open_checking(client, user, balance=100_000, per_transfer_limit=50_000, daily_transfer_limit=50_000)
    res = await send(client, user, source["account_id"], "110-123-0007")
    assert res.status_code == 400
    error = res.json()["error"]
    assert error["code"] == "INTERBANK_FAILED" and error["extra"]["fail_code"] == "ACCOUNT_NOT_FOUND"
    assert error["extra"]["balance_after"] == 100_000
    assert await balance_of(client, user, source["account_id"]) == 100_000
    assert await history_types(client, user, source["account_id"]) == [("TRANSFER_OUT", -30_000), ("TRANSFER_REFUND", 30_000)]
    assert (await interbank_list(client, user))[0]["status"] == "FAILED"

    # 되돌려 받은 금액은 1일 한도에서 빠진다 (50,000 한도에 30,000을 다시 보낼 수 있음)
    res = await send(client, user, source["account_id"], "110-123-0001")
    assert res.status_code == 200, res.text


async def test_send_pending_then_confirmed(client, user, hub):
    source = await open_checking(client, user, balance=100_000)
    res = await send(client, user, source["account_id"], "110-123-0003")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["status"] == "PENDING" and data["balance_after"] == 70_000
    assert "확인 중" in res.json()["message"]

    async with SessionLocal() as db:
        assert await confirm_pending(db) == 0  # 허브도 아직 PENDING
    hub.transfers[data["transfer_id"]]["status"] = "COMPLETED"
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    assert (await interbank_list(client, user))[0]["status"] == "COMPLETED"
    assert await balance_of(client, user, source["account_id"]) == 70_000


async def test_send_pending_then_failed_refunds(client, user, hub):
    source = await open_checking(client, user, balance=100_000)
    tid = (await send(client, user, source["account_id"], "110-123-0003")).json()["data"]["transfer_id"]
    hub.transfers[tid].update(status="FAILED", fail_code="ACCOUNT_INACTIVE", fail_message="정지 계좌")
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    [row] = await interbank_list(client, user)
    assert (row["status"], row["fail_code"]) == ("FAILED", "ACCOUNT_INACTIVE")
    assert await balance_of(client, user, source["account_id"]) == 100_000


async def test_hub_no_answer_keeps_money_pending_then_resends(client, user, hub):
    """허브가 응답 없음 → 출금은 유지하고 PENDING (되돌리지 않음). 확인 때 허브가 모르면(404) 같은 ID로 다시 보낸다."""
    source = await open_checking(client, user, balance=100_000)
    hub.hub_down = True
    res = await send(client, user, source["account_id"], "110-123-0006")
    data = res.json()["data"]
    assert data["status"] == "PENDING"
    assert await balance_of(client, user, source["account_id"]) == 70_000

    hub.hub_down = False
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    assert [c["transfer_id"] for c in hub.transfer_calls] == [data["transfer_id"]] * 2  # 같은 ID로 재전송
    assert hub.transfers[data["transfer_id"]]["status"] == "COMPLETED"
    assert (await interbank_list(client, user))[0]["status"] == "COMPLETED"


async def test_send_respects_limits_and_balance(client, user, hub):
    source = await open_checking(client, user, balance=10_000)
    res = await send(client, user, source["account_id"], "110-123-0001")
    assert res.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert hub.transfer_calls == []


# ── 모아 대화 (확인 카드) ───────────────────────────────────────

async def test_chat_interbank_card_and_approve(client, user, hub, classify):
    """"SimBank 110-123-0001로 5만원 보내줘" → 받는 분 확인(허브) → 확인 카드(은행 포함) → 승인 → 완료"""
    source = await open_checking(client, user, balance=100_000)
    session_id = await new_chat_session(client, user)
    classify.next(intent="transfer", bank_name="SimBank", to_account_num="110-123-0001", amount=50_000)
    reply = await say(client, user, session_id, "SimBank 110-123-0001로 5만원 보내줘")
    card = reply["card"]
    assert (card["to_bank"], card["to_bank_name"], card["holder_name"], card["to_account_num"]) == (
        "902", "SimBank", "김철수", "110-123-0001")
    assert "SimBank 김철수님께 5만원을 보낼까요?" in reply["content"]
    assert card["tts_text"].startswith("SimBank 김철수님께 5만원을 보냅니다.")
    assert hub.transfer_calls == []  # 카드까지는 돈이 안 움직인다

    # 카드와 다른 은행으로 바꿔 보내면 거절 (같은 번호의 우리 은행 계좌로 바꿔치기 방지)
    res = await client.post("/transfers", headers=user, json=approve(card, session_id))
    assert res.json()["error"]["code"] == "CONFIRMATION_MISMATCH"

    res = await client.post("/transfers", headers=user, json=approve(card, session_id, to_bank="902"))
    assert res.status_code == 200, res.text
    assert res.json()["data"]["status"] == "COMPLETED"
    assert await balance_of(client, user, source["account_id"]) == 50_000
    [call] = hub.transfer_calls
    assert (call["to_account"], call["amount"]) == ("110-123-0001", 50_000)

    res = await client.post("/transfers", headers=user, json=approve(card, session_id, to_bank="902"))
    assert res.json()["error"]["code"] == "CONFIRMATION_USED"  # 카드는 한 번만


async def test_chat_interbank_asks_account_number(client, user, hub, classify):
    await open_checking(client, user, balance=100_000)
    session_id = await new_chat_session(client, user)
    classify.next(intent="transfer", bank_name="simbank 은행", amount=50_000)  # 대소문자·띄어쓰기·"은행"은 무시
    reply = await say(client, user, session_id, "SimBank로 5만원 보내줘")
    assert reply["card"] is None and "SimBank 계좌번호를 알려 주세요" in reply["content"]

    classify.next(intent="transfer", to_account_num="110-123-0001")
    reply = await say(client, user, session_id, "110-123-0001이야")
    assert reply["card"], reply["content"]
    assert reply["card"]["to_bank"] == "902" and reply["card"]["amount"] == 50_000


async def test_chat_interbank_unknown_bank_and_account(client, user, hub, classify):
    await open_checking(client, user, balance=100_000)
    session_id = await new_chat_session(client, user)
    classify.next(intent="transfer", bank_name="없는은행", to_account_num="110-123-0001", amount=50_000)
    reply = await say(client, user, session_id, "없는은행 110-123-0001로 5만원")
    assert reply["card"] is None and "찾지 못했어요" in reply["content"] and "SimBank" in reply["content"]

    classify.next(intent="transfer", bank_name="SimBank", to_account_num="110-123-0002", amount=50_000)
    reply = await say(client, user, session_id, "SimBank 110-123-0002로 5만원")
    assert reply["card"] is None and "SimBank에서 그 계좌를 찾을 수 없어요" in reply["content"]


async def test_chat_interbank_pending_and_fds(client, user, hub, classify, monkeypatch):
    """처리 중(PENDING)도 카드 승인으로 가고, 대화 속 보이스피싱 정황은 타행 이체에도 FDS로 걸린다"""
    source = await open_checking(client, user, balance=100_000)
    session_id = await new_chat_session(client, user)
    classify.next(intent="transfer", bank_name="SimBank", to_account_num="110-123-0003", amount=30_000)
    card = (await say(client, user, session_id, "SimBank 110-123-0003으로 3만원"))["card"]
    res = await client.post("/transfers", headers=user, json=approve(card, session_id, to_bank="902"))
    assert res.json()["data"]["status"] == "PENDING"

    other = await new_chat_session(client, user)
    classify.next(intent="transfer", bank_name="SimBank", to_account_num="110-123-0001", amount=60_000)
    card = (await say(client, user, other, "검찰청에서 안전계좌로 옮기래요. SimBank 110-123-0001로 6만원"))["card"]
    res = await client.post("/transfers", headers=user, json=approve(card, other, to_bank="902"))
    error = res.json()["error"]
    assert error["code"] in ("FDS_BLOCKED", "ADDITIONAL_AUTH_REQUIRED")
    assert any(h["code"].startswith("CONVERSATION") for h in error["extra"]["rule_hits"])
    assert await balance_of(client, user, source["account_id"]) == 70_000  # 막힌 이체는 출금 안 됨


async def test_own_bank_code_is_internal_transfer(client, user, other_user, hub):
    source = await open_checking(client, user, balance=100_000)
    target = await open_checking(client, other_user)
    res = await client.post("/transfers", headers=user, json={
        "from_checking_account_id": source["account_id"], "to_bank": "901",
        "to_account_num": target["account_num"], "amount": 10_000,
    })
    assert res.status_code == 200 and res.json()["data"]["to_bank"] is None
    assert hub.transfer_calls == []


async def test_holder_inquiry(client, user, other_user, hub):
    target = await open_checking(client, other_user)
    own = await client.post("/transfers/inquiry", headers=user, json={"to_account_num": target["account_num"]})
    assert own.json()["data"] == {"to_bank": "901", "bank_name": "AvengersBank", "to_account_num": target["account_num"],
                                  "holder_name": "브루스 배너"}
    ext = await client.post("/transfers/inquiry", headers=user, json={"to_bank": "902", "to_account_num": "110-123-0001"})
    assert (ext.json()["data"]["bank_name"], ext.json()["data"]["holder_name"]) == ("SimBank", "김철수")
    missing = await client.post("/transfers/inquiry", headers=user, json={"to_bank": "902", "to_account_num": "110-123-0002"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    unknown = await client.post("/transfers/inquiry", headers=user, json={"to_bank": "777", "to_account_num": "110-123-0001"})
    assert unknown.json()["error"]["code"] == "BANK_NOT_FOUND"
    own_missing = await client.post("/transfers/inquiry", headers=user, json={"to_account_num": "110-000-000000"})
    assert own_missing.status_code == 404


# ── 받기 (허브 → 우리) ─────────────────────────────────────────

async def hub_call(client, method: str, path: str, payload: dict | None = None, secret: str = SECRET):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() if payload is not None else b""
    headers = {"X-Bank-Code": "000", "Content-Type": "application/json", **sign(secret, body)}
    return await client.request(method, path, content=body, headers=headers)


def receive_payload(account_num: str, transfer_id: str = "7c9e6679-7425-40de-944b-e07fc1f90ae7") -> dict:
    return {"transfer_id": transfer_id, "from_bank": "902", "from_bank_name": "SimBank", "from_account": "110-200-456789",
            "to_account": account_num, "amount": 25_000, "sender_name": "김철수", "memo": "생활비"}


async def test_receive_once(client, user):
    account = await open_checking(client, user, balance=1_000)
    res = await hub_call(client, "POST", "/interbank/inquiry", {"account_num": account["account_num"]})
    assert res.json() == {"holder_name": "토니 스타크"}

    payload = receive_payload(account["account_num"])
    first = await hub_call(client, "POST", "/interbank/receive", payload)
    again = await hub_call(client, "POST", "/interbank/receive", payload)  # 허브 재전송
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json() == {"transfer_id": payload["transfer_id"], "status": "COMPLETED", "holder_name": "토니 스타크"}
    assert await balance_of(client, user, account["account_id"]) == 26_000
    assert await history_types(client, user, account["account_id"]) == [("TRANSFER_IN", 25_000)]

    status = await hub_call(client, "GET", f"/interbank/receive/{payload['transfer_id']}")
    assert status.json()["status"] == "COMPLETED"
    missing = await hub_call(client, "GET", "/interbank/receive/00000000-0000-4000-8000-000000000000")
    assert missing.status_code == 404 and missing.json()["error"] == "TRANSFER_NOT_FOUND"


async def test_receive_errors_use_spec_format(client, user):
    res = await hub_call(client, "POST", "/interbank/receive", receive_payload("110-999-999999"))
    assert res.status_code == 404 and res.json()["error"] == "ACCOUNT_NOT_FOUND"
    res = await hub_call(client, "POST", "/interbank/inquiry", {"account_num": "110-999-999999"})
    assert res.status_code == 404 and res.json()["error"] == "ACCOUNT_NOT_FOUND"
    res = await hub_call(client, "POST", "/interbank/receive", {**receive_payload("x"), "amount": -1})
    assert res.status_code == 422 and res.json()["error"] == "VALIDATION_ERROR"


async def test_unexpected_error_uses_spec_format(client, user, monkeypatch):
    """처리하지 못한 예외도 SPEC 5절 형식의 500 (허브는 5xx면 재시도한다)"""
    from avengers_bank.domains.interbank import service

    async def broken(db, data):
        raise RuntimeError("DB 끊김")

    monkeypatch.setattr(service, "receive", broken)
    account = await open_checking(client, user)
    res = await hub_call(client, "POST", "/interbank/receive", receive_payload(account["account_num"]))
    assert res.status_code == 500
    body = res.json()
    assert body["error"] == "INTERNAL_ERROR" and body["message"]
    assert "DB 끊김" not in res.text  # 내부 사정은 밖으로 내보내지 않는다


async def test_receive_rejects_bad_signature(client, user):
    account = await open_checking(client, user)
    res = await hub_call(client, "POST", "/interbank/receive", receive_payload(account["account_num"]), secret="wrong")
    assert res.status_code == 401 and res.json()["error"] == "SIGNATURE_INVALID"
    res = await client.post("/interbank/receive", json=receive_payload(account["account_num"]))  # 서명 없음
    assert res.status_code == 401
    assert await balance_of(client, user, account["account_id"]) == 0
