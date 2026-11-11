"""다른 은행 이체 (ClearingHub 연동). 허브는 이 파일의 가짜 허브(SPEC 3절)로 대신한다.

가짜 허브의 받는 계좌번호 끝 4자리:
  0001 완료 · 0002 조회부터 계좌 없음 · 0003 202 PENDING(나중에 허브 결과가 바뀜)
  0006 허브가 응답 안 함(요청도 저장 안 함) · 0007 조회는 되는데 이체에서 받는 은행이 거절

가짜 허브는 실제 허브(SPEC v1.0 2절)처럼 Ed25519만 받는다: 우리 요청을 등록된 우리 공개키로 검증하고, /v1 응답(2xx·4xx)에
허브 키로 응답 서명(SPEC 2.5)을 붙인다. 키는 conftest의 테스트 키다. 서명을 망가뜨리는 시험은 test_nonrepudiation.py.
"""

import asyncio
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank.hub_client import hub_client
from avengers_bank.domains.interbank.response_signing import ResponseSigningMiddleware
from avengers_bank.domains.interbank.service import confirm_pending, ledger_balances, reconcile, settlement_positions
from avengers_bank.domains.interbank.signing import (
    fingerprint, generate_keypair, is_valid_key, public_key_of, sign_ed25519, verify_ed25519, verify_response,
)
from tests.conftest import TEST_BANK_PUBLIC, TEST_HUB_PRIVATE, new_chat_session, open_checking
from tests.test_chat import approve, classify, say  # noqa: F401  classify는 fixture

pytestmark = pytest.mark.anyio
HUB_PRIVATE = TEST_HUB_PRIVATE  # 가짜 허브의 개인키 (우리 HUB_PUBLIC_KEY의 짝)
WRONG_HUB_PRIVATE, _ = generate_keypair()  # 허브인 척하는 다른 키


class FakeHub:
    def __init__(self):
        self.app = FastAPI()
        self.transfers: dict[str, dict] = {}  # 허브가 저장한 거래
        self.transfer_calls: list[dict] = []
        self.hub_down = False
        self.request_ids: list[tuple[str, str | None]] = []  # (경로, 받은 X-Request-ID)
        # 서명 (SPEC 2절·2.5·2.6)
        self.bank_public_key: str | None = TEST_BANK_PUBLIC  # 등록된 우리 공개키 (PUT /v1/keys로 바뀐다)
        self.hub_key: str | None = HUB_PRIVATE  # 허브 개인키. /v1 응답(2xx·4xx)에 응답 서명
        self.reply_key: str | None = None  # 응답 서명에 대신 쓸 키 (틀린 서명 시험)
        self.sign_replies = True  # False면 응답 서명을 빼먹는다
        self.algs: list[tuple[str, str]] = []  # (경로, 받은 서명 방식)
        self.transfer_raw: list[tuple[dict, bytes]] = []  # POST /v1/transfers의 (헤더, 원본 바이트)
        # 등록·셀프 서비스 (SPEC 3.5·3.6)
        self.invite_code: str | None = "inv_test_invite"  # 쓰면 None
        self.register_calls: list[tuple[dict, dict]] = []  # POST /v1/banks/register의 (헤더, 본문)
        self.bank: AsyncClient | None = None  # ping이 부를 우리 앱 (hub 픽스처가 넣는다)
        self.ping_public_key: str | None = None  # ping의 응답 서명 검증에 대신 쓸 공개키 (틀린 응답 서명 시험)
        self._routes()
        # 허브의 core/response_signing.py와 같은 일을 우리 미들웨어로 한다 (서명 값은 test_nonrepudiation K1로 SPEC과 맞춘다)
        self.asgi = ResponseSigningMiddleware(self.app, key_getter=self._reply_key, path_prefix="/v1/")

    def _reply_key(self) -> str | None:
        return (self.reply_key or self.hub_key) if self.sign_replies else None

    def _routes(self):
        app = self.app

        async def check(request: Request) -> bytes | JSONResponse:
            self.request_ids.append((request.url.path, request.headers.get("x-request-id")))
            body = await request.body()
            alg = (request.headers.get("x-signature-alg") or "ed25519").lower()  # 없으면 ed25519 (SPEC 2.1)
            self.algs.append((request.url.path, alg))
            args = (request.headers.get("x-timestamp"), request.method, request.url.path, body, request.headers.get("x-signature"))
            ok = (request.headers.get("x-bank-code") == "901" and request.headers.get("x-api-key") == "chk_test_api_key"
                  and alg == "ed25519" and verify_ed25519(self.bank_public_key, *args) is None)
            return body if ok else JSONResponse(status_code=401, content={"error": "SIGNATURE_INVALID", "message": "서명"})

        @app.get("/v1/hub-key")
        async def hub_key():
            if self.hub_key is None:
                return JSONResponse(status_code=404, content={"error": "HUB_KEY_MISSING", "message": "허브 키 없음"})
            public = public_key_of(self.hub_key)
            return {"algorithm": "ed25519", "public_key": public, "fingerprint": fingerprint(public)}

        def key_status(previous: str | None = None) -> dict:
            return {"bank_code": "901", "fingerprint": fingerprint(self.bank_public_key) if self.bank_public_key else None,
                    "registered_at": "2026-11-06T03:00:00Z",
                    "previous_fingerprint": fingerprint(previous) if previous else None,
                    "previous_key_expires_at": "2026-11-07T03:00:00Z" if previous else None,
                    "hub_fingerprint": fingerprint(public_key_of(self.hub_key)) if self.hub_key else None}

        @app.put("/v1/keys")
        async def put_keys(request: Request):
            if isinstance(body := await check(request), JSONResponse):
                return body
            public = json.loads(body).get("public_key")
            if not is_valid_key(public):
                return JSONResponse(status_code=422, content={"error": "VALIDATION_ERROR", "message": "공개키"})
            previous = self.bank_public_key if self.bank_public_key not in (None, public) else None
            self.bank_public_key = public  # 옛 키를 24시간 더 받는 것은 흉내 내지 않는다
            return key_status(previous)

        @app.get("/v1/keys")
        async def get_keys(request: Request):
            if isinstance(r := await check(request), JSONResponse):
                return r
            return key_status()

        async def ping() -> dict:
            """허브의 ping_bank(SPEC 3.6)처럼: 없는 계좌로 우리 /interbank/inquiry를 허브 키로 서명해 부르고,
            우리 응답 서명을 등록된 우리 공개키로 검증한다. 우리 앱은 hub 픽스처가 넣은 self.bank로 부른다."""
            body = b'{"account_num":"000-000-000000"}'
            headers = {"X-Bank-Code": "000", "Content-Type": "application/json",
                       **sign_ed25519(self.hub_key, "POST", "/inquiry", body)}
            res = await self.bank.post("/interbank/inquiry", content=body, headers=headers)
            valid = None if res.status_code >= 500 else verify_response(
                self.ping_public_key or self.bank_public_key, res.headers.get("x-response-timestamp"), res.status_code, headers["X-Signature"],
                res.content, res.headers.get("x-response-signature")) is None
            data = res.json() if res.content else {}
            ok = valid is True and (res.status_code == 200 or (res.status_code == 404 and data.get("error") == "ACCOUNT_NOT_FOUND"))
            return {"ok": ok, "reachable": True, "status": res.status_code, "body": data, "response_signature_valid": valid}

        @app.get("/v1/me")
        async def me(request: Request):
            if isinstance(r := await check(request), JSONResponse):
                return r
            return {"bank_code": "901", "name": "AvengersBank", "base_url": "http://test/interbank", "active": True,
                    "net_debit_cap": 0, "public_key_fingerprint": fingerprint(self.bank_public_key),
                    "created_at": "2026-11-05T00:00:00Z"}

        @app.post("/v1/me/ping")
        async def me_ping(request: Request):
            if isinstance(r := await check(request), JSONResponse):
                return r
            return await ping()

        @app.post("/v1/banks/register")
        async def register(request: Request):
            """셀프 등록 (SPEC 3.5, 인증 없음). 은행 코드는 허브가 정한다 (903). 응답 서명의 request_signature는 ""."""
            data = json.loads(await request.body())
            self.register_calls.append((dict(request.headers), data))
            if data.get("invite_code") != self.invite_code:
                return JSONResponse(status_code=400, content={"error": "INVITE_INVALID", "message": "초대 코드"})
            if not is_valid_key(data.get("public_key")):
                return JSONResponse(status_code=422, content={"error": "VALIDATION_ERROR", "message": "public_key"})
            self.invite_code = None  # 한 번만
            self.bank_public_key = data["public_key"]
            hub_public = public_key_of(self.hub_key)
            return JSONResponse(status_code=201, content={
                "bank_code": "903", "name": data["name"], "api_key": "chk_new_bank_api_key", "hub_public_key": hub_public,
                "hub_fingerprint": fingerprint(hub_public), "net_debit_cap": 1_000_000_000, "ping": await ping()})

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
            self.transfer_raw.append((dict(request.headers), body))
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
    fake.bank = client
    http = AsyncClient(transport=ASGITransport(app=fake.asgi), base_url="http://hub")
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


async def books() -> dict[str, int]:
    """내부 계정 잔액. 대사(분개 잔액 = 거래 기록)가 맞는지도 함께 확인한다."""
    async with SessionLocal() as db:
        assert await reconcile(db) == []
    async with SessionLocal() as db, db.begin():
        return {k: v for k, v in (await ledger_balances(db)).items() if v or k == "INTERBANK_SUSPENSE"}


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
    assert await books() == {"INTERBANK_SUSPENSE": 0, "INTERBANK_SETTLEMENT:902": 30_000}


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
    assert await books() == {"INTERBANK_SUSPENSE": 0}


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
    assert await books() == {"INTERBANK_SUSPENSE": 0}

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

    assert await books() == {"INTERBANK_SUSPENSE": 30_000}  # 출금됐지만 확정 전: 중간 계정에 있다
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 0  # 허브도 아직 PENDING
    hub.transfers[data["transfer_id"]]["status"] = "COMPLETED"
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    assert (await interbank_list(client, user))[0]["status"] == "COMPLETED"
    assert await balance_of(client, user, source["account_id"]) == 70_000
    assert await books() == {"INTERBANK_SUSPENSE": 0, "INTERBANK_SETTLEMENT:902": 30_000}


async def test_send_pending_then_failed_refunds(client, user, hub):
    source = await open_checking(client, user, balance=100_000)
    tid = (await send(client, user, source["account_id"], "110-123-0003")).json()["data"]["transfer_id"]
    hub.transfers[tid].update(status="FAILED", fail_code="ACCOUNT_INACTIVE", fail_message="정지 계좌")
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    [row] = await interbank_list(client, user)
    assert (row["status"], row["fail_code"]) == ("FAILED", "ACCOUNT_INACTIVE")
    assert await balance_of(client, user, source["account_id"]) == 100_000
    assert await books() == {"INTERBANK_SUSPENSE": 0}


async def test_hub_no_answer_keeps_money_pending_then_resends(client, user, hub):
    """허브가 응답 없음 → 출금은 유지하고 PENDING (되돌리지 않음). 확인 때 허브가 모르면(404) 같은 ID로 다시 보낸다."""
    source = await open_checking(client, user, balance=100_000)
    hub.hub_down = True
    res = await send(client, user, source["account_id"], "110-123-0006")
    data = res.json()["data"]
    assert data["status"] == "PENDING"
    assert await balance_of(client, user, source["account_id"]) == 70_000
    assert await books() == {"INTERBANK_SUSPENSE": 30_000}

    hub.hub_down = False
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    assert [c["transfer_id"] for c in hub.transfer_calls] == [data["transfer_id"]] * 2  # 같은 ID로 재전송
    assert hub.transfers[data["transfer_id"]]["status"] == "COMPLETED"
    assert (await interbank_list(client, user))[0]["status"] == "COMPLETED"
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 0  # 이미 확정된 거래는 다시 분개하지 않는다
    assert await books() == {"INTERBANK_SUSPENSE": 0, "INTERBANK_SETTLEMENT:902": 30_000}


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

async def hub_call(client, method: str, path: str, payload: dict | None = None, key: str = HUB_PRIVATE,
                   signed_path: str | None = None):
    """허브처럼 Ed25519로 서명해 부른다 (SPEC 2.3). 서명 경로는 base_url(/interbank) 뒤의 부분이다 (SPEC 2.2)."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() if payload is not None else b""
    signed_path = path.partition("/interbank")[2] if signed_path is None else signed_path
    headers = {"X-Bank-Code": "000", "Content-Type": "application/json", **sign_ed25519(key, method, signed_path, body)}
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
    assert await books() == {"INTERBANK_SUSPENSE": 0, "INTERBANK_SETTLEMENT:902": -25_000}  # 902가 우리에게 줄 돈

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
    res = await hub_call(client, "POST", "/interbank/receive", receive_payload(account["account_num"]), key=WRONG_HUB_PRIVATE)
    assert res.status_code == 401 and res.json()["error"] == "SIGNATURE_INVALID"
    # 다른 경로용 서명을 붙여 와도 거절한다 (서명에 메서드·경로가 들어간다)
    res = await hub_call(client, "POST", "/interbank/receive", receive_payload(account["account_num"]),
                         signed_path="/inquiry")
    assert res.status_code == 401 and res.json()["error"] == "SIGNATURE_INVALID"
    res = await hub_call(client, "POST", "/interbank/receive", receive_payload(account["account_num"]),
                         signed_path="/interbank/receive")  # 실제 경로가 아니라 base_url 뒤의 부분으로 서명해야 한다
    assert res.status_code == 401
    res = await client.post("/interbank/receive", json=receive_payload(account["account_num"]))  # 서명 없음
    assert res.status_code == 401
    assert await balance_of(client, user, account["account_id"]) == 0


# ── 내부 계정 (중간 계정·정산 계정) ─────────────────────────────

async def test_settlement_nets_both_directions(client, user, hub):
    """보낸 30,000 + 받은 25,000 → 902 정산 계정 순액 +5,000 (우리가 줄 돈). 허브 정산표와 같은 모양"""
    from datetime import timedelta

    from avengers_bank.core.clock import now_utc

    source = await open_checking(client, user, balance=100_000)
    assert (await send(client, user, source["account_id"], "110-123-0001")).status_code == 200
    assert (await hub_call(client, "POST", "/interbank/receive", receive_payload(source["account_num"]))).status_code == 200
    assert await books() == {"INTERBANK_SUSPENSE": 0, "INTERBANK_SETTLEMENT:902": 5_000}

    now = now_utc()
    async with SessionLocal() as db:
        positions = await settlement_positions(db, now - timedelta(hours=1), now + timedelta(hours=1))
    assert positions == [{"bank_code": "902", "sent": 30_000, "received": 25_000, "net": 5_000}]
    async with SessionLocal() as db:
        assert await settlement_positions(db, now + timedelta(hours=1), now + timedelta(hours=2)) == []


async def test_reconcile_detects_drift(client, user, hub):
    """거래 기록만 바뀌고 분개가 따라가지 않으면(직접 DB 수정, 버그) 대사가 어긋남을 알린다"""
    from sqlalchemy import update

    from avengers_bank.domains.interbank.models import InterbankTransfer

    source = await open_checking(client, user, balance=100_000)
    tid = (await send(client, user, source["account_id"], "110-123-0003")).json()["data"]["transfer_id"]
    await books()
    async with SessionLocal() as db, db.begin():
        await db.execute(update(InterbankTransfer).where(InterbankTransfer.transfer_id == tid).values(status="COMPLETED"))
    async with SessionLocal() as db:
        problems = await reconcile(db)
    assert len(problems) == 2
    assert problems[0].startswith("INTERBANK_SETTLEMENT:902") and problems[1].startswith("INTERBANK_SUSPENSE")


# ── 멱등성: 출금이 커밋된 뒤의 실패 ─────────────────────────────────

async def test_retry_after_failure_post_debit_does_not_debit_twice(client, user, hub, monkeypatch):
    """출금 커밋 뒤 허브를 부르기 전에 오류가 나도(요청 취소·DB 오류와 같은 경로) 키가 풀리지 않는다.
    같은 키로 다시 보내면 새로 출금하지 않고 처음 이체의 상태를 돌려준다."""
    from avengers_bank.domains.interbank import service as interbank_service

    real_deliver = interbank_service.deliver

    async def broken(db, transfer_id):
        raise RuntimeError("허브 호출 전에 연결이 끊김")

    monkeypatch.setattr(interbank_service, "deliver", broken)
    source = await open_checking(client, user, balance=100_000)
    headers = {**user, "Idempotency-Key": "interbank-key-0001"}

    with pytest.raises(RuntimeError):  # 테스트 클라이언트는 처리 못 한 예외를 500 대신 그대로 올린다
        await send(client, headers, source["account_id"], "110-123-0001")
    assert await balance_of(client, user, source["account_id"]) == 70_000  # 출금은 커밋됐다
    [row] = await interbank_list(client, user)
    assert row["status"] == "PENDING" and hub.transfer_calls == []

    again = await send(client, headers, source["account_id"], "110-123-0001")
    assert again.status_code == 200, again.text
    assert again.headers["idempotent-replayed"] == "true"
    data = again.json()["data"]
    assert (data["transfer_id"], data["status"], data["balance_after"]) == (row["transfer_id"], "PENDING", 70_000)
    assert await balance_of(client, user, source["account_id"]) == 70_000  # 두 번 빠지지 않았다
    assert len(await interbank_list(client, user)) == 1
    assert await history_types(client, user, source["account_id"]) == [("TRANSFER_OUT", -30_000)]

    # 워커가 허브에 물어보고(404) 같은 transfer_id로 다시 보내 확정하면, 같은 키 재시도도 완료로 답한다
    monkeypatch.setattr(interbank_service, "deliver", real_deliver)
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    third = await send(client, headers, source["account_id"], "110-123-0001")
    assert third.status_code == 200 and third.json()["data"]["status"] == "COMPLETED"
    assert len(hub.transfer_calls) == 1
    assert await books() == {"INTERBANK_SUSPENSE": 0, "INTERBANK_SETTLEMENT:902": 30_000}


async def test_retry_of_refunded_interbank_replays_failure(client, user, hub):
    """받는 은행이 거절해 되돌린 이체에 같은 키로 다시 오면, 다시 출금·전송하지 않고 같은 실패를 돌려준다."""
    source = await open_checking(client, user, balance=100_000)
    headers = {**user, "Idempotency-Key": "interbank-key-0002"}

    first = await send(client, headers, source["account_id"], "110-123-0007")
    assert first.status_code == 400 and first.json()["error"]["code"] == "INTERBANK_FAILED"
    again = await send(client, headers, source["account_id"], "110-123-0007")
    assert again.status_code == 400
    error = again.json()["error"]
    assert error["code"] == "INTERBANK_FAILED" and error["extra"]["transfer_id"] == first.json()["error"]["extra"]["transfer_id"]
    assert len(hub.transfer_calls) == 1 and len(await interbank_list(client, user)) == 1
    assert await balance_of(client, user, source["account_id"]) == 100_000
    assert await history_types(client, user, source["account_id"]) == [("TRANSFER_OUT", -30_000), ("TRANSFER_REFUND", 30_000)]


async def test_interbank_success_with_key_replays_stored_response(client, user, hub):
    source = await open_checking(client, user, balance=100_000)
    headers = {**user, "Idempotency-Key": "interbank-key-0003"}
    first = await send(client, headers, source["account_id"], "110-123-0001")
    again = await send(client, headers, source["account_id"], "110-123-0001")
    assert again.status_code == 200 and again.headers["idempotent-replayed"] == "true"
    assert again.json() == first.json()
    assert len(hub.transfer_calls) == 1
    assert await balance_of(client, user, source["account_id"]) == 70_000
