"""부인방지: Ed25519 요청 서명·응답 서명·증거 보관 (ClearingHub SPEC v1.0 2.3·2.5·2.6, SETTLEMENT_PLAN 12.8·12.11).

서명은 Ed25519 하나다. 허브는 test_interbank.py의 가짜 허브(Ed25519만 받고 응답에 서명)를 쓴다. 허브 → 우리 요청은
허브처럼 서명해 직접 부른다. 우리·허브 키는 conftest의 테스트 키다 (SPEC 2.3의 예시 키는 K1에만 쓴다).
"""

import hashlib
import hmac
import json
import time

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from avengers_bank.core.config import Settings, get_settings
from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank import keys
from avengers_bank.domains.interbank.evidence import list_for_transfer
from avengers_bank.domains.interbank.models import HubEvidence
from avengers_bank.domains.interbank.service import confirm_pending
from avengers_bank.domains.interbank.signing import (
    fingerprint, generate_keypair, public_key_of, sign_ed25519, sign_response, verify_ed25519, verify_response,
)
from tests.conftest import TEST_BANK_PRIVATE, TEST_BANK_PUBLIC, TEST_HUB_PRIVATE, TEST_HUB_PUBLIC, open_checking
from tests.test_interbank import balance_of, books, hub, interbank_list, receive_payload, send  # noqa: F401

pytestmark = pytest.mark.anyio

BANK_PRIVATE, BANK_PUBLIC = TEST_BANK_PRIVATE, TEST_BANK_PUBLIC  # 우리(901) 키 (INTERBANK_SIGNING_KEY)
HUB_PRIVATE, HUB_PUBLIC = TEST_HUB_PRIVATE, TEST_HUB_PUBLIC  # 가짜 허브 키 (HUB_PUBLIC_KEY)
OTHER_PRIVATE, OTHER_PUBLIC = generate_keypair()  # 아무도 등록하지 않은 키 (다른 은행·꾸민 서명)


# ── K1: SPEC 2.3·2.5의 고정 값 ───────────────────────────────────

EXAMPLE_BANK_PRIVATE = "D7frsUqSl9ZuC+7EpHfY1+w6+dAlWqg8vuHVtZfdpg4="
EXAMPLE_BANK_PUBLIC = "gxCDPKbN/rIXKDJgn4GZh5JY7I65Cwbk3A/mJjTtPzY="
EXAMPLE_HUB_PRIVATE = "cycR/h4ydSTPkBGuRFO340cDtdAdwrXQjKC4N1GPgtQ="
EXAMPLE_HUB_PUBLIC = "yZdBWoR7swp/3CQvh4c58oahhbjxVeaxWWtqmqwDXdo="
EXAMPLE_TID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


def _compact(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()


def test_k1_spec_examples():
    """SPEC 2.3 예시 1·2와 2.5 예시 3. Ed25519는 같은 키·메시지면 서명이 늘 같다."""
    body = _compact({"transfer_id": EXAMPLE_TID, "to_bank": "902", "to_account": "110-123-0001",
                     "from_account": "110-200-456789", "amount": 50000, "sender_name": "홍길동", "memo": "생활비"})
    assert len(body) == 190

    assert public_key_of(EXAMPLE_BANK_PRIVATE) == EXAMPLE_BANK_PUBLIC
    assert public_key_of(EXAMPLE_HUB_PRIVATE) == EXAMPLE_HUB_PUBLIC
    assert (fingerprint(EXAMPLE_BANK_PUBLIC), fingerprint(EXAMPLE_HUB_PUBLIC)) == ("d61a340fe933017d", "239a9acfc7ecb8de")

    e1 = sign_ed25519(EXAMPLE_BANK_PRIVATE, "POST", "/v1/transfers", body, timestamp=1762300800)
    assert e1 == {"X-Timestamp": "1762300800", "X-Signature-Alg": "ed25519", "X-Signature":
                  "SY/3NCjTxAR1dC5UXHM/PkQZR9/SMa+wcDBSIrAit0jeHW5JKKgw4vZWKiN2Z7o5V+ywCY7EyWsTEfLf/F3mBw=="}
    assert verify_ed25519(EXAMPLE_BANK_PUBLIC, "1762300800", "POST", "/v1/transfers", body, e1["X-Signature"],
                          max_skew=None) is None

    path = f"/receive/{EXAMPLE_TID}"
    e2 = sign_ed25519(EXAMPLE_HUB_PRIVATE, "GET", path, b"", timestamp=1762300800)
    assert e2["X-Signature"] == "IMn6yCKkn/eZGPNY74b3+cNvA/4ax9knE97hh4wCQnPEHe6IEdKREh/Pit3+7bJJjx801OiRbJIvJD0HbKzPAA=="
    assert verify_ed25519(EXAMPLE_HUB_PUBLIC, "1762300800", "GET", path, b"", e2["X-Signature"], max_skew=None) is None

    reply = _compact({"transfer_id": EXAMPLE_TID, "status": "COMPLETED", "holder_name": "김철수",
                      "received_at": "2026-11-05T01:20:02Z"})
    assert len(reply) == 138
    e3 = sign_response(EXAMPLE_BANK_PRIVATE, 200, e2["X-Signature"], reply, timestamp=1762300801)
    assert e3 == {"X-Response-Timestamp": "1762300801", "X-Signature-Alg": "ed25519", "X-Response-Signature":
                  "D84tooOZEJ6jehp/BN6dVPw1KZCB+eejxpZOqgggeTW7iJznoyNjQGEFwShbhnX7prHkg9uG9e7rP9IxZS91Dg=="}
    assert verify_response(EXAMPLE_BANK_PUBLIC, "1762300801", 200, e2["X-Signature"], reply,
                           e3["X-Response-Signature"], max_skew=None) is None
    # K7: 같은 응답을 다른 요청(예시 1)에 붙이면 틀린다. 상태 코드를 바꿔도 틀린다
    assert verify_response(EXAMPLE_BANK_PUBLIC, "1762300801", 200, e1["X-Signature"], reply,
                           e3["X-Response-Signature"], max_skew=None) == "SIGNATURE_INVALID"
    assert verify_response(EXAMPLE_BANK_PUBLIC, "1762300801", 404, e2["X-Signature"], reply,
                           e3["X-Response-Signature"], max_skew=None) == "SIGNATURE_INVALID"


@pytest.mark.parametrize("public_key, signature", [
    ("not-base64!", "x" * 88),
    (EXAMPLE_BANK_PUBLIC[:-4], "A" * 86 + "=="),  # 키 길이가 틀림
    (EXAMPLE_BANK_PUBLIC, "A" * 84 + "===="),  # base64가 아님
    (EXAMPLE_BANK_PUBLIC, "QUJD"),  # 서명 길이가 틀림
    (EXAMPLE_BANK_PUBLIC, "한" * 88),  # 비 ASCII
    (EXAMPLE_BANK_PUBLIC, "0" * 64),  # 예전 HMAC 서명(hex 64자)
    (None, None),
])
def test_bad_key_or_signature_is_invalid_not_exception(public_key, signature):
    ts = str(int(time.time()))
    assert verify_ed25519(public_key, ts, "POST", "/receive", b"{}", signature) == "SIGNATURE_INVALID"
    assert verify_response(public_key, ts, 200, "", b"{}", signature) == "SIGNATURE_INVALID"


def test_tamper_and_skew():
    headers = sign_ed25519(BANK_PRIVATE, "POST", "/v1/transfers", b'{"amount":1}')
    args = (headers["X-Timestamp"], "POST", "/v1/transfers")
    assert verify_ed25519(BANK_PUBLIC, *args, b'{"amount":1}', headers["X-Signature"]) is None
    assert verify_ed25519(BANK_PUBLIC, *args, b'{"amount":2}', headers["X-Signature"]) == "SIGNATURE_INVALID"
    assert verify_ed25519(HUB_PUBLIC, *args, b'{"amount":1}', headers["X-Signature"]) == "SIGNATURE_INVALID"
    old = sign_ed25519(BANK_PRIVATE, "POST", "/v1/transfers", b"", timestamp=int(time.time()) - 301)
    assert verify_ed25519(BANK_PUBLIC, old["X-Timestamp"], "POST", "/v1/transfers", b"", old["X-Signature"]) == "SIGNATURE_EXPIRED"


def test_settings_keys_and_enabled():
    """키 형식이 틀리면 앱이 뜨지 않는다. 빈 값은 없는 것으로 본다. 타행 이체는 네 설정이 다 있어야 켜진다.
    예전 .env의 HUB_SECRET·INTERBANK_SIGNATURE_MODE가 남아 있어도 무시한다 (시작은 된다)."""
    base = {"_env_file": None, "hub_url": "http://hub", "hub_api_key": "chk_x"}
    with pytest.raises(ValidationError, match="INTERBANK_SIGNING_KEY는"):
        Settings(**base, interbank_signing_key="not-a-key")
    with pytest.raises(ValidationError, match="HUB_PUBLIC_KEY는"):
        Settings(**base, hub_public_key=HUB_PUBLIC[:-1])
    empty = Settings(**base, interbank_signing_key="", hub_public_key=" ")
    assert (empty.interbank_signing_key, empty.hub_public_key) == (None, None)
    assert not empty.interbank_enabled and empty.interbank_missing == ["INTERBANK_SIGNING_KEY", "HUB_PUBLIC_KEY"]
    no_hub_key = Settings(**base, interbank_signing_key=BANK_PRIVATE, hub_public_key="")
    assert no_hub_key.interbank_missing == ["HUB_PUBLIC_KEY"]
    ok = Settings(**base, interbank_signing_key=f" {BANK_PRIVATE}\n", hub_public_key=HUB_PUBLIC,
                  hub_secret="old-secret", interbank_signature_mode="hmac")
    assert ok.interbank_enabled and ok.interbank_signing_key.get_secret_value() == BANK_PRIVATE
    assert not hasattr(ok, "hub_secret") and not hasattr(ok, "interbank_signature_mode")


# ── 도우미 ──────────────────────────────────────────────────────

async def hub_call_raw(client, method: str, path: str, payload: dict | None = None, key: str = HUB_PRIVATE,
                       alg: str | None = None):
    """허브처럼 Ed25519로 서명해 부른다 (SPEC 2.3). (응답, 보낸 헤더, 보낸 본문). alg를 주면 X-Signature-Alg를 그 값으로."""
    body = _compact(payload) if payload is not None else b""
    headers = {"X-Bank-Code": "000", "Content-Type": "application/json",
               **sign_ed25519(key, method, path.partition("/interbank")[2], body)}
    if alg is not None:
        headers["X-Signature-Alg"] = alg
    return await client.request(method, path, content=body, headers=headers), headers, body


def old_hmac_headers(method: str, path: str, body: bytes) -> dict[str, str]:
    """8c 이전 허브의 HMAC 서명 (hex). 이제는 받지 않는다."""
    ts = str(int(time.time()))
    digest = hmac.new(b"old-hub-secret", f"{ts}\n{method}\n{path}\n".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Bank-Code": "000", "Content-Type": "application/json", "X-Timestamp": ts, "X-Signature": digest}


def assert_reply_signed_by_us(response, request_signature: str) -> None:
    """우리 응답 서명이 우리 공개키로 검증되고, 그 요청에 묶여 있다 (SPEC 2.5)."""
    assert response.headers["x-signature-alg"] == "ed25519"
    assert verify_response(BANK_PUBLIC, response.headers["x-response-timestamp"], response.status_code,
                           request_signature, response.content, response.headers["x-response-signature"]) is None
    assert verify_response(BANK_PUBLIC, response.headers["x-response-timestamp"], response.status_code,
                           "other-request", response.content, response.headers["x-response-signature"]) == "SIGNATURE_INVALID"


async def evidence(transfer_id: str) -> list[HubEvidence]:
    async with SessionLocal() as db:
        return await list_for_transfer(db, transfer_id)


# ── 왕복 ────────────────────────────────────────────────────────

async def test_send_round_trip(client, user, hub):
    """우리 → 허브: Ed25519로 서명해 보내고, 허브 응답 서명을 허브 공개키로 검증해 COMPLETED. 원문이 증거로 남는다."""
    source = await open_checking(client, user, balance=100_000)
    res = await send(client, user, source["account_id"], "110-123-0001")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["status"] == "COMPLETED"
    assert {alg for _, alg in hub.algs} == {"ed25519"}  # 예금주 조회·이체 모두
    assert all(headers["x-signature-alg"] == "ed25519" for headers, _ in hub.transfer_raw)
    assert await books() == {"INTERBANK_SUSPENSE": 0, "INTERBANK_SETTLEMENT:902": 30_000}

    out, reply = await evidence(data["transfer_id"])
    [(hub_headers, hub_body)] = hub.transfer_raw
    assert (out.direction, out.method, out.path, out.signature_alg, out.signature_valid) == (
        "TRANSFER_OUT", "POST", "/v1/transfers", "ed25519", None)
    assert out.body == hub_body  # 허브가 받은 바이트와 같다
    assert out.headers_json["X-Signature"] == hub_headers["x-signature"]
    assert "X-Api-Key" not in out.headers_json
    # 나중에 제3자가 다시 검증할 수 있다: 요청은 우리 공개키로, 응답은 허브 공개키 + 요청 서명으로
    assert verify_ed25519(BANK_PUBLIC, out.headers_json["X-Timestamp"], out.method, out.path, out.body,
                          out.headers_json["X-Signature"], max_skew=None) is None
    assert (reply.direction, reply.http_status, reply.signature_alg, reply.signature_valid) == (
        "TRANSFER_REPLY", 200, "ed25519", True)
    assert json.loads(reply.body)["status"] == "COMPLETED"
    assert verify_response(HUB_PUBLIC, reply.headers_json["X-Response-Timestamp"], reply.http_status,
                           out.headers_json["X-Signature"], reply.body, reply.headers_json["X-Response-Signature"],
                           max_skew=None) is None


async def test_receive_and_status(client, user, hub):
    """허브 → 우리: Ed25519 /receive로 입금, 우리 응답에 우리 키의 응답 서명. /receive/{id}도. 요청·응답 원문이 남는다."""
    account = await open_checking(client, user, balance=1_000)
    inquiry, sent, _ = await hub_call_raw(client, "POST", "/interbank/inquiry", {"account_num": account["account_num"]})
    assert inquiry.json() == {"holder_name": "토니 스타크"}
    assert_reply_signed_by_us(inquiry, sent["X-Signature"])

    payload = receive_payload(account["account_num"])
    first, first_headers, first_body = await hub_call_raw(client, "POST", "/interbank/receive", payload)
    again, again_headers, _ = await hub_call_raw(client, "POST", "/interbank/receive", payload)  # 허브 재전송
    assert first.status_code == again.status_code == 200
    assert first.json()["status"] == "COMPLETED"
    assert_reply_signed_by_us(first, first_headers["X-Signature"])
    assert_reply_signed_by_us(again, again_headers["X-Signature"])
    assert await balance_of(client, user, account["account_id"]) == 26_000  # 입금 1번

    status, status_headers, _ = await hub_call_raw(client, "GET", f"/interbank/receive/{payload['transfer_id']}")
    assert status.json()["status"] == "COMPLETED"
    assert_reply_signed_by_us(status, status_headers["X-Signature"])
    missing, missing_headers, _ = await hub_call_raw(client, "GET", "/interbank/receive/00000000-0000-4000-8000-000000000000")
    assert missing.status_code == 404
    assert_reply_signed_by_us(missing, missing_headers["X-Signature"])  # 4xx에도 붙인다

    rows = await evidence(payload["transfer_id"])
    assert [r.direction for r in rows] == ["RECEIVE_IN", "RECEIVE_REPLY"] * 3
    for request_row, reply_row, response, headers in zip(rows[::2], rows[1::2], (first, again, status),
                                                         (first_headers, again_headers, status_headers)):
        assert (request_row.signature_alg, request_row.signature_valid) == ("ed25519", True)
        assert request_row.headers_json["X-Signature"] == headers["X-Signature"]
        assert verify_ed25519(HUB_PUBLIC, request_row.headers_json["X-Timestamp"], request_row.method, request_row.path,
                              request_row.body, request_row.headers_json["X-Signature"], max_skew=None) is None
        assert (reply_row.http_status, reply_row.signature_alg, reply_row.signature_valid) == (200, "ed25519", None)
        assert reply_row.body == response.content  # 허브가 받은 응답 바이트 그대로
        assert reply_row.headers_json["X-Response-Signature"] == response.headers["x-response-signature"]
    assert rows[0].body == first_body and rows[0].path == "/receive"
    assert (rows[4].method, rows[4].path, rows[4].body) == ("GET", f"/receive/{payload['transfer_id']}", b"")
    assert [r.http_status for r in await evidence("00000000-0000-4000-8000-000000000000")] == [None, 404]


async def test_omitted_alg_header_means_ed25519(client, user):
    """X-Signature-Alg는 생략할 수 있고, 없으면 ed25519로 본다 (SPEC 2.1)."""
    account = await open_checking(client, user)
    body = _compact({"account_num": account["account_num"]})
    headers = {"X-Bank-Code": "000", "Content-Type": "application/json",
               **sign_ed25519(HUB_PRIVATE, "POST", "/inquiry", body)}
    del headers["X-Signature-Alg"]
    res = await client.post("/interbank/inquiry", content=body, headers=headers)
    assert res.status_code == 200
    assert_reply_signed_by_us(res, headers["X-Signature"])


async def test_rejects_non_ed25519_or_unsigned_hub_requests(client, user):
    """K3·K4·K5: 예전 HMAC 허브 요청(헤더 없음·`hmac`), 모르는 방식, 다른 키, 서명 없음은 모두 401. 입금도 증거도 없다.
    401 응답에도 우리 응답 서명이 붙는다 (SPEC 2.5)."""
    account = await open_checking(client, user)
    payload = receive_payload(account["account_num"])
    body = _compact(payload)

    old = old_hmac_headers("POST", "/receive", body)  # 8c 이전 허브: X-Signature-Alg 없음 = 예전엔 HMAC
    res = await client.post("/interbank/receive", content=body, headers=old)
    assert res.status_code == 401 and res.json()["error"] == "SIGNATURE_INVALID"
    assert_reply_signed_by_us(res, old["X-Signature"])

    res = await client.post("/interbank/receive", content=body, headers={**old, "X-Signature-Alg": "hmac"})
    assert res.status_code == 401 and res.json()["error"] == "SIGNATURE_INVALID"
    assert "ed25519만" in res.json()["message"]
    assert_reply_signed_by_us(res, old["X-Signature"])

    weird, weird_headers, _ = await hub_call_raw(client, "POST", "/interbank/receive", payload, alg="rsa")  # 서명은 맞음
    assert weird.status_code == 401 and weird.json()["error"] == "SIGNATURE_INVALID"
    other, other_headers, _ = await hub_call_raw(client, "POST", "/interbank/receive", payload, key=OTHER_PRIVATE)
    assert other.status_code == 401 and other.json()["error"] == "SIGNATURE_INVALID"
    assert_reply_signed_by_us(other, other_headers["X-Signature"])

    unsigned = await client.post("/interbank/receive", content=body,
                                 headers={"X-Bank-Code": "000", "Content-Type": "application/json"})
    assert unsigned.status_code == 401 and unsigned.json()["error"] == "UNAUTHORIZED"
    assert_reply_signed_by_us(unsigned, "")  # 요청에 서명이 없으면 request_signature는 ""

    assert await balance_of(client, user, account["account_id"]) == 0
    assert await evidence(payload["transfer_id"]) == []  # 검증을 통과하지 못한 요청은 남기지 않는다


# ── 허브 응답 서명이 틀림·없음 ──────────────────────────────────

def break_replies(hub, broken: str) -> None:
    if broken == "wrong":
        hub.reply_key = OTHER_PRIVATE  # 허브 공개키로 검증되지 않는 서명
    else:
        hub.sign_replies = False


class AfterTransfer(list):
    """가짜 허브가 이체 요청을 받아 기록한 직후 hook을 부른다 (예금주 조회 응답은 정상, 이체 응답부터 망가뜨릴 때)."""

    def __init__(self, hook):
        super().__init__()
        self.hook = hook

    def append(self, item):
        super().append(item)
        self.hook()


@pytest.mark.parametrize("broken", ["wrong", "missing"])
async def test_bad_hub_reply_signature_blocks_inquiry(client, user, hub, broken):
    """예금주 조회 응답의 서명이 틀리면 그 이름을 믿지 않는다: 503 (돈은 움직이기 전이다)."""
    break_replies(hub, broken)
    res = await client.post("/transfers/inquiry", headers=user, json={"to_bank": "902", "to_account_num": "110-123-0001"})
    assert res.status_code == 503


@pytest.mark.parametrize("broken", ["wrong", "missing"])
async def test_bad_hub_reply_signature_keeps_transfer_pending(client, user, hub, broken):
    """허브 응답 서명이 틀리거나 없으면 "응답 없음": 이체는 PENDING 그대로(되돌리지 않음). 결과 조회(서명 맞음)로 확정."""
    source = await open_checking(client, user, balance=100_000)
    hub.transfer_raw = AfterTransfer(lambda: break_replies(hub, broken))
    res = await send(client, user, source["account_id"], "110-123-0001")
    data = res.json()["data"]
    assert data["status"] == "PENDING"  # 허브는 COMPLETED라고 답했지만 증명할 수 없으므로 모른다
    assert await balance_of(client, user, source["account_id"]) == 70_000
    _, reply = await evidence(data["transfer_id"])
    assert (reply.direction, reply.http_status, reply.signature_valid) == ("TRANSFER_REPLY", 200, False)
    assert (reply.signature_alg is None) == (broken == "missing")

    async with SessionLocal() as db:
        assert await confirm_pending(db) == 0  # 결과 조회 응답도 서명이 틀려 아직 모른다
    hub.reply_key, hub.sign_replies = None, True
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    assert (await interbank_list(client, user))[0]["status"] == "COMPLETED"
    assert len(await evidence(data["transfer_id"])) == 2  # 결과 조회는 증거로 남기지 않는다
    assert await books() == {"INTERBANK_SUSPENSE": 0, "INTERBANK_SETTLEMENT:902": 30_000}


async def test_bad_signature_on_rejection_does_not_refund(client, user, hub):
    """4xx라도 서명이 틀리면 거절로 믿지 않는다 (되돌렸는데 실제로 접수됐다면 두 번 나간다). 확인 뒤에 되돌린다."""
    source = await open_checking(client, user, balance=100_000)
    hub.transfer_raw = AfterTransfer(lambda: break_replies(hub, "wrong"))
    res = await send(client, user, source["account_id"], "110-123-0007")  # 허브가 404 FAILED로 답함
    assert res.json()["data"]["status"] == "PENDING"
    assert await balance_of(client, user, source["account_id"]) == 70_000
    hub.reply_key = None
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    assert (await interbank_list(client, user))[0]["status"] == "FAILED"
    assert await balance_of(client, user, source["account_id"]) == 100_000


async def test_5xx_is_not_signed(client, user, hub, monkeypatch):
    """5xx는 본문 보장이 없어 서명하지 않는다 (SPEC 2.5). 허브는 그대로 재시도한다."""
    from avengers_bank.domains.interbank import service

    async def broken(db, data):
        raise RuntimeError("DB 끊김")

    monkeypatch.setattr(service, "receive", broken)
    account = await open_checking(client, user)
    res, _, _ = await hub_call_raw(client, "POST", "/interbank/receive", receive_payload(account["account_num"]))
    assert res.status_code == 500 and "x-response-signature" not in res.headers
    [request_row] = await evidence(receive_payload("x")["transfer_id"])  # 요청은 처리 전에 남는다
    assert request_row.direction == "RECEIVE_IN"


async def test_prod_mount_path_is_signed(client, user, hub):
    """운영(/api 아래 마운트)에서도 /api/interbank/* 응답에 서명하고, 서명 경로는 /interbank 뒤의 부분이다."""
    from httpx import ASGITransport, AsyncClient

    from avengers_bank.prod import app as prod_app

    account = await open_checking(client, user)
    async with AsyncClient(transport=ASGITransport(app=prod_app), base_url="http://test") as prod:
        res, headers, _ = await hub_call_raw(prod, "POST", "/api/interbank/inquiry", {"account_num": account["account_num"]})
    assert res.status_code == 200, res.text
    assert_reply_signed_by_us(res, headers["X-Signature"])
    assert "x-response-signature" not in (await client.get("/health")).headers  # /interbank 밖은 그대로


async def test_interbank_disabled_without_keys(client, user, monkeypatch):
    """키 중 하나라도 없으면 타행 이체가 꺼진다: 보내기는 503, /interbank/*도 503.
    HUB_API_KEY만 없으면(셀프 등록 직후) 보내기는 꺼져도 허브 요청은 받는다 (등록 응답의 ping이 통과해야 하므로)."""
    account = await open_checking(client, user)
    monkeypatch.setattr(get_settings(), "hub_api_key", None)
    res, headers, _ = await hub_call_raw(client, "POST", "/interbank/inquiry", {"account_num": account["account_num"]})
    assert res.status_code == 200
    assert_reply_signed_by_us(res, headers["X-Signature"])
    res = await client.post("/transfers/inquiry", headers=user, json={"to_bank": "902", "to_account_num": "110-123-0001"})
    assert res.status_code == 503

    monkeypatch.setattr(get_settings(), "hub_public_key", None)
    res, _, _ = await hub_call_raw(client, "POST", "/interbank/inquiry", {"account_num": account["account_num"]})
    assert res.status_code == 503 and res.json()["error"] == "INTERBANK_DISABLED"


async def test_evidence_rows(client, user, hub):
    """이체 원문만 남는다 (TRANSFER_OUT·TRANSFER_REPLY 모두 ed25519). 결과 조회·예금주 조회는 남기지 않는다."""
    source = await open_checking(client, user, balance=100_000)
    tid = (await send(client, user, source["account_id"], "110-123-0001")).json()["data"]["transfer_id"]
    async with SessionLocal() as db, db.begin():
        rows = list(await db.scalars(select(HubEvidence)))
    assert [(r.transfer_id, r.direction, r.signature_alg) for r in rows] == [
        (tid, "TRANSFER_OUT", "ed25519"), (tid, "TRANSFER_REPLY", "ed25519")]


# ── 키 도구 (keys.py) ───────────────────────────────────────────

async def test_keys_generate(capsys):
    assert await keys.run(["generate"]) == 0
    out = capsys.readouterr().out
    private = out.split("INTERBANK_SIGNING_KEY, 서버 .env에만): ")[1].split()[0]
    public = out.split("비밀 아님):")[1].split()[0]
    assert public_key_of(private) == public and fingerprint(public) in out


async def test_keys_hub_key(client, hub, monkeypatch, capsys):
    assert await keys.run(["hub-key"]) == 0
    out = capsys.readouterr().out
    assert HUB_PUBLIC in out and fingerprint(HUB_PUBLIC) in out

    monkeypatch.setattr(get_settings(), "hub_public_key", OTHER_PUBLIC)
    assert await keys.run(["hub-key"]) == 1  # 설정된 HUB_PUBLIC_KEY와 다르다
    assert "다릅니다" in capsys.readouterr().err
    hub.hub_key = None
    assert await keys.run(["hub-key"]) == 1  # 허브가 키를 주지 않음 (404)


async def test_keys_register_bank(client, hub, monkeypatch, capsys):
    """새 환경의 셀프 등록: HUB_API_KEY 없이, 서명 헤더 없이 POST /v1/banks/register. 우리 개인키의 공개키를 보낸다.
    응답의 bank_code·api_key·hub_fingerprint·ping을 보여 주고, 허브의 ping(우리 /interbank/inquiry)이 정상이면 0."""
    monkeypatch.setattr(get_settings(), "hub_api_key", None)
    hub.bank_public_key = None  # 아직 등록되지 않은 은행
    argv = ["register-bank", "--invite-code", "inv_test_invite", "--name", "NewBank", "--base-url", "http://test/interbank/"]
    assert await keys.run(argv) == 0
    out = capsys.readouterr().out
    [(headers, sent)] = hub.register_calls
    assert sent == {"invite_code": "inv_test_invite", "name": "NewBank", "base_url": "http://test/interbank",
                    "public_key": BANK_PUBLIC}
    assert not {"x-signature", "x-api-key", "x-bank-code", "x-timestamp"} & set(headers)
    assert "bank_code 903" in out and "api_key: chk_new_bank_api_key" in out
    assert f"hub_fingerprint: {fingerprint(HUB_PUBLIC)}" in out and "ok: True" in out
    assert "BANK_CODE=903" in out
    assert hub.bank_public_key == BANK_PUBLIC

    assert await keys.run(argv) == 1  # 초대 코드는 한 번만
    assert "INVITE_INVALID" in capsys.readouterr().out


async def test_keys_register_bank_warns_on_bad_hub_signature(client, hub, monkeypatch, capsys):
    """등록 응답의 허브 서명이 틀리면 api_key는 보여 주되(이 응답에만 있다) 경고하고 1로 끝낸다."""
    hub.reply_key = OTHER_PRIVATE
    argv = ["register-bank", "--invite-code", "inv_test_invite", "--name", "NewBank", "--base-url", "http://test/interbank"]
    assert await keys.run(argv) == 1
    captured = capsys.readouterr()
    assert "api_key: chk_new_bank_api_key" in captured.out
    assert "허브 서명이 HUB_PUBLIC_KEY로 검증되지 않습니다" in captured.err

    monkeypatch.setattr(get_settings(), "interbank_signing_key", None)
    assert await keys.run(argv) == 2  # 개인키가 없으면 부르지도 않는다
    assert "INTERBANK_SIGNING_KEY" in capsys.readouterr().err


async def test_keys_ping_and_status(client, hub, capsys):
    """ping: 허브가 우리 /interbank/inquiry를 불러 본 결과. status: /v1/me + /v1/keys와 우리 키 지문 대조."""
    assert await keys.run(["ping"]) == 0
    out = capsys.readouterr().out
    assert "ok: True" in out and "status: 404" in out and "response_signature_valid: True" in out

    assert await keys.run(["status"]) == 0
    out = capsys.readouterr().out
    assert "bank_code: 901" in out and f"public_key_fingerprint: {fingerprint(BANK_PUBLIC)}" in out
    assert f"hub_fingerprint: {fingerprint(HUB_PUBLIC)}" in out

    hub.bank_public_key = OTHER_PUBLIC  # 허브에 다른 공개키가 등록돼 있음 → 우리 요청부터 401
    assert await keys.run(["ping"]) == 1
    assert await keys.run(["status"]) == 1


async def test_keys_ping_reports_bad_reply_signature(client, hub, capsys):
    """허브가 우리 응답 서명을 검증하지 못하면 ping은 ok False, response_signature_valid False (이체가 PENDING에 쌓일 상태)."""
    hub.ping_public_key = OTHER_PUBLIC  # 허브가 응답 서명 검증에 다른 공개키를 쓴다
    assert await keys.run(["ping"]) == 1
    out = capsys.readouterr().out
    assert "ok: False" in out and "response_signature_valid: False" in out and "INTERBANK_SIGNING_KEY" in out


async def test_keys_rotate(client, hub, capsys):
    """회전: 새 공개키를 지금(옛) 키의 Ed25519 서명으로 등록한다 (SPEC 2.6)."""
    _, new_public = generate_keypair()
    assert await keys.run(["register", "--public-key", new_public]) == 0
    assert hub.algs[-1] == ("/v1/keys", "ed25519") and hub.bank_public_key == new_public
    out = capsys.readouterr().out
    assert f"이전 키 {fingerprint(BANK_PUBLIC)}" in out
    assert await keys.run(["register", "--public-key", "short"]) == 2


async def test_keys_register_needs_registered_key(client, hub, capsys):
    """register는 지금 키가 허브에 등록돼 있어야 한다. 아니면 허브가 401 → register-bank나 관리자 등록을 안내."""
    hub.bank_public_key = OTHER_PUBLIC
    assert await keys.run(["register"]) == 1
    assert "register-bank" in capsys.readouterr().err
