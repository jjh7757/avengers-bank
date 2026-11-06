"""부인방지: Ed25519 요청 서명·응답 서명·증거 보관 (ClearingHub SPEC v1.0 2.3·2.5·2.6, SETTLEMENT_PLAN 12.8).

허브는 test_interbank.py의 가짜 허브를 Ed25519로 켜서 쓴다 (mode·우리 공개키·허브 키). 허브 → 우리 요청은
허브처럼 서명해 직접 부른다. 허브·우리 테스트 키는 이 파일에서 만든다 (SPEC 2.3의 예시 키는 K1에만 쓴다).
"""

import json
import time

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from avengers_bank.core.config import Settings, get_settings
from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank import keys
from avengers_bank.domains.interbank.evidence import list_for_transfer
from avengers_bank.domains.interbank.models import HubEvidence
from avengers_bank.domains.interbank.service import confirm_pending
from avengers_bank.domains.interbank.signing import (
    fingerprint, generate_keypair, public_key_of, sign, sign_ed25519, sign_response, verify, verify_ed25519,
    verify_response,
)
from tests.conftest import open_checking
from tests.test_interbank import SECRET, balance_of, books, hub, hub_call, interbank_list, receive_payload, send  # noqa: F401

pytestmark = pytest.mark.anyio

BANK_PRIVATE, BANK_PUBLIC = generate_keypair()  # 우리(901) 키
HUB_PRIVATE, HUB_PUBLIC = generate_keypair()  # 가짜 허브 키
OTHER_PRIVATE, _ = generate_keypair()  # 아무도 등록하지 않은 키 (다른 은행·꾸민 서명)


# ── K1: SPEC 2.3·2.5의 고정 값 ───────────────────────────────────

EXAMPLE_BANK_PRIVATE = "D7frsUqSl9ZuC+7EpHfY1+w6+dAlWqg8vuHVtZfdpg4="
EXAMPLE_BANK_PUBLIC = "gxCDPKbN/rIXKDJgn4GZh5JY7I65Cwbk3A/mJjTtPzY="
EXAMPLE_HUB_PRIVATE = "cycR/h4ydSTPkBGuRFO340cDtdAdwrXQjKC4N1GPgtQ="
EXAMPLE_HUB_PUBLIC = "yZdBWoR7swp/3CQvh4c58oahhbjxVeaxWWtqmqwDXdo="
EXAMPLE_TID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


def _compact(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()


def test_k1_spec_examples():
    """SPEC 2.3 예시 1·2(HMAC·Ed25519)와 2.5 예시 3. Ed25519는 같은 키·메시지면 서명이 늘 같다."""
    body = _compact({"transfer_id": EXAMPLE_TID, "to_bank": "902", "to_account": "110-123-0001",
                     "from_account": "110-200-456789", "amount": 50000, "sender_name": "홍길동", "memo": "생활비"})
    assert len(body) == 190
    assert sign("example-secret-change-me", "POST", "/v1/transfers", body, 1762300800)["X-Signature"] == \
        "1afb099015e80126587211e3a2ef82bfbb9c0a4af2d9065519029985e7797f65"

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
    assert verify(SECRET, old["X-Timestamp"], "POST", "/v1/transfers", b"", "0" * 64) == "SIGNATURE_EXPIRED"


def test_settings_check_keys():
    """ed25519 모드인데 키가 없거나, 키 형식이 틀리면 앱이 뜨지 않는다. 빈 값은 없는 것으로 본다."""
    base = {"_env_file": None}
    with pytest.raises(ValidationError, match="INTERBANK_SIGNING_KEY와 HUB_PUBLIC_KEY"):
        Settings(**base, interbank_signature_mode="ed25519", interbank_signing_key=BANK_PRIVATE)
    with pytest.raises(ValidationError, match="INTERBANK_SIGNING_KEY는"):
        Settings(**base, interbank_signing_key="not-a-key")
    with pytest.raises(ValidationError, match="HUB_PUBLIC_KEY는"):
        Settings(**base, hub_public_key=HUB_PUBLIC[:-1])
    with pytest.raises(ValidationError):
        Settings(**base, interbank_signature_mode="rsa")
    empty = Settings(**base, interbank_signing_key="", hub_public_key=" ")
    assert (empty.interbank_signing_key, empty.hub_public_key, empty.interbank_signature_mode) == (None, None, "hmac")
    ok = Settings(**base, interbank_signature_mode="ed25519", interbank_signing_key=f" {BANK_PRIVATE}\n", hub_public_key=HUB_PUBLIC)
    assert ok.interbank_signing_key.get_secret_value() == BANK_PRIVATE


# ── 픽스처 ──────────────────────────────────────────────────────

def use_mode(monkeypatch, hub, mode: str, *, signing_key: str | None = BANK_PRIVATE) -> None:
    """우리 설정과 가짜 허브를 같은 모드로 (허브 관리자가 정한 모드와 같게 둔다)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "interbank_signing_key", SecretStr(signing_key) if signing_key else None)
    monkeypatch.setattr(settings, "hub_public_key", HUB_PUBLIC)
    monkeypatch.setattr(settings, "interbank_signature_mode", mode)
    hub.mode, hub.bank_public_key, hub.hub_key = mode, BANK_PUBLIC, HUB_PRIVATE


@pytest.fixture
async def ed25519(hub, monkeypatch):
    use_mode(monkeypatch, hub, "ed25519")
    return hub


async def hub_call_ed25519(client, method: str, path: str, payload: dict | None = None, key: str = HUB_PRIVATE):
    """허브처럼 Ed25519로 서명해 부른다 (SPEC 2.3). (응답, 보낸 헤더, 보낸 본문)."""
    body = _compact(payload) if payload is not None else b""
    headers = {"X-Bank-Code": "000", "Content-Type": "application/json",
               **sign_ed25519(key, method, path.partition("/interbank")[2], body)}
    return await client.request(method, path, content=body, headers=headers), headers, body


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


# ── ed25519 모드 왕복 ───────────────────────────────────────────

async def test_ed25519_send_round_trip(client, user, ed25519):
    """우리 → 허브: Ed25519로 서명해 보내고, 허브 응답 서명을 허브 공개키로 검증해 COMPLETED. 원문이 증거로 남는다."""
    source = await open_checking(client, user, balance=100_000)
    res = await send(client, user, source["account_id"], "110-123-0001")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["status"] == "COMPLETED"
    assert {alg for _, alg in ed25519.algs} == {"ed25519"}  # 예금주 조회·이체 모두
    assert await books() == {"INTERBANK_SUSPENSE": 0, "INTERBANK_SETTLEMENT:902": 30_000}

    out, reply = await evidence(data["transfer_id"])
    [(hub_headers, hub_body)] = ed25519.transfer_raw
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


async def test_ed25519_receive_and_status(client, user, ed25519):
    """허브 → 우리: Ed25519 /receive로 입금, 우리 응답에 우리 키의 응답 서명. /receive/{id}도. 요청·응답 원문이 남는다."""
    account = await open_checking(client, user, balance=1_000)
    inquiry, sent, _ = await hub_call_ed25519(client, "POST", "/interbank/inquiry", {"account_num": account["account_num"]})
    assert inquiry.json() == {"holder_name": "토니 스타크"}
    assert_reply_signed_by_us(inquiry, sent["X-Signature"])

    payload = receive_payload(account["account_num"])
    first, first_headers, first_body = await hub_call_ed25519(client, "POST", "/interbank/receive", payload)
    again, again_headers, _ = await hub_call_ed25519(client, "POST", "/interbank/receive", payload)  # 허브 재전송
    assert first.status_code == again.status_code == 200
    assert first.json()["status"] == "COMPLETED"
    assert_reply_signed_by_us(first, first_headers["X-Signature"])
    assert_reply_signed_by_us(again, again_headers["X-Signature"])
    assert await balance_of(client, user, account["account_id"]) == 26_000  # 입금 1번

    status, status_headers, _ = await hub_call_ed25519(client, "GET", f"/interbank/receive/{payload['transfer_id']}")
    assert status.json()["status"] == "COMPLETED"
    assert_reply_signed_by_us(status, status_headers["X-Signature"])
    missing, missing_headers, _ = await hub_call_ed25519(client, "GET", "/interbank/receive/00000000-0000-4000-8000-000000000000")
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


async def test_ed25519_mode_rejects_hmac_from_hub(client, user, ed25519):
    """K3·K5: ed25519 모드에서는 HMAC(허브 secret으로 만든 진짜 HMAC이라도) 요청을 받지 않는다. K4: 다른 키도 거절."""
    account = await open_checking(client, user)
    payload = receive_payload(account["account_num"])
    hmac_res = await hub_call(client, "POST", "/interbank/receive", payload)  # X-Signature-Alg 없음 = HMAC
    assert hmac_res.status_code == 401 and hmac_res.json()["error"] == "SIGNATURE_INVALID"
    assert "ed25519 모드" in hmac_res.json()["message"]
    other, _, _ = await hub_call_ed25519(client, "POST", "/interbank/receive", payload, key=OTHER_PRIVATE)
    assert other.status_code == 401 and other.json()["error"] == "SIGNATURE_INVALID"
    weird = await client.post("/interbank/receive", content=_compact(payload), headers={
        "X-Bank-Code": "000", "X-Signature-Alg": "rsa", **sign(SECRET, "POST", "/receive", _compact(payload))})
    assert weird.status_code == 401 and weird.json()["error"] == "SIGNATURE_INVALID"
    assert hmac_res.headers.get("x-response-signature")  # 거절 응답(4xx)에도 응답 서명은 붙는다
    assert await balance_of(client, user, account["account_id"]) == 0
    assert await evidence(payload["transfer_id"]) == []  # 검증을 통과하지 못한 요청은 남기지 않는다


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
async def test_bad_hub_reply_signature_blocks_inquiry(client, user, ed25519, broken):
    """예금주 조회 응답의 서명이 틀리면 그 이름을 믿지 않는다: 503 (돈은 움직이기 전이다)."""
    break_replies(ed25519, broken)
    res = await client.post("/transfers/inquiry", headers=user, json={"to_bank": "902", "to_account_num": "110-123-0001"})
    assert res.status_code == 503


@pytest.mark.parametrize("broken", ["wrong", "missing"])
async def test_bad_hub_reply_signature_keeps_transfer_pending(client, user, ed25519, broken):
    """허브 응답 서명이 틀리거나 없으면 "응답 없음": 이체는 PENDING 그대로(되돌리지 않음). 결과 조회(서명 맞음)로 확정."""
    source = await open_checking(client, user, balance=100_000)
    ed25519.transfer_raw = AfterTransfer(lambda: break_replies(ed25519, broken))
    res = await send(client, user, source["account_id"], "110-123-0001")
    data = res.json()["data"]
    assert data["status"] == "PENDING"  # 허브는 COMPLETED라고 답했지만 증명할 수 없으므로 모른다
    assert await balance_of(client, user, source["account_id"]) == 70_000
    _, reply = await evidence(data["transfer_id"])
    assert (reply.direction, reply.http_status, reply.signature_valid) == ("TRANSFER_REPLY", 200, False)
    assert (reply.signature_alg is None) == (broken == "missing")

    async with SessionLocal() as db:
        assert await confirm_pending(db) == 0  # 결과 조회 응답도 서명이 틀려 아직 모른다
    ed25519.reply_key, ed25519.sign_replies = None, True
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    assert (await interbank_list(client, user))[0]["status"] == "COMPLETED"
    assert len(await evidence(data["transfer_id"])) == 2  # 결과 조회는 증거로 남기지 않는다
    assert await books() == {"INTERBANK_SUSPENSE": 0, "INTERBANK_SETTLEMENT:902": 30_000}


async def test_bad_signature_on_rejection_does_not_refund(client, user, ed25519):
    """4xx라도 서명이 틀리면 거절로 믿지 않는다 (되돌렸는데 실제로 접수됐다면 두 번 나간다). 확인 뒤에 되돌린다."""
    source = await open_checking(client, user, balance=100_000)
    ed25519.transfer_raw = AfterTransfer(lambda: break_replies(ed25519, "wrong"))
    res = await send(client, user, source["account_id"], "110-123-0007")  # 허브가 404 FAILED로 답함
    assert res.json()["data"]["status"] == "PENDING"
    assert await balance_of(client, user, source["account_id"]) == 70_000
    ed25519.reply_key = None
    async with SessionLocal() as db:
        assert await confirm_pending(db) == 1
    assert (await interbank_list(client, user))[0]["status"] == "FAILED"
    assert await balance_of(client, user, source["account_id"]) == 100_000


# ── both·hmac 모드 ──────────────────────────────────────────────

async def test_both_mode(client, user, hub, monkeypatch):
    """K2: both는 Ed25519로 보내고, 허브 요청은 HMAC·Ed25519 둘 다 받는다. 허브 응답 서명이 틀려도 기록만 한다."""
    use_mode(monkeypatch, hub, "both")
    source = await open_checking(client, user, balance=100_000)
    hub.reply_key = OTHER_PRIVATE
    res = await send(client, user, source["account_id"], "110-123-0001")
    assert res.json()["data"]["status"] == "COMPLETED"  # both 모드는 응답 서명으로 동작을 바꾸지 않는다
    assert {alg for _, alg in hub.algs} == {"ed25519"}
    _, reply = await evidence(res.json()["data"]["transfer_id"])
    assert reply.signature_valid is False

    hmac_res = await hub_call(client, "POST", "/interbank/receive", receive_payload(source["account_num"]))
    assert hmac_res.status_code == 200
    assert_reply_signed_by_us(hmac_res, hmac_res.request.headers["x-signature"])  # HMAC 요청의 서명(hex)에 묶는다
    ed_res, _, _ = await hub_call_ed25519(client, "POST", "/interbank/receive",
                                          receive_payload(source["account_num"], "11111111-1111-4111-8111-111111111111"))
    assert ed_res.status_code == 200
    assert await balance_of(client, user, source["account_id"]) == 120_000
    [hmac_in, _] = await evidence(receive_payload("x")["transfer_id"])
    assert (hmac_in.signature_alg, hmac_in.signature_valid) == ("hmac", True)


async def test_both_mode_without_key_sends_hmac(client, user, hub, monkeypatch):
    """both인데 우리 키를 아직 안 넣었으면 HMAC으로 보낸다 (허브는 both에서 둘 다 받는다). 응답 서명도 없다."""
    use_mode(monkeypatch, hub, "both", signing_key=None)
    source = await open_checking(client, user, balance=100_000)
    assert (await send(client, user, source["account_id"], "110-123-0001")).json()["data"]["status"] == "COMPLETED"
    assert {alg for _, alg in hub.algs} == {"hmac"}
    res = await hub_call(client, "POST", "/interbank/inquiry", {"account_num": source["account_num"]})
    assert res.status_code == 200 and "x-response-signature" not in res.headers


async def test_hmac_mode_is_unchanged(client, user, hub, monkeypatch):
    """기본(hmac): X-Signature-Alg 없이 HMAC으로 보내고, Ed25519 허브 요청은 받지 않는다. 키를 넣으면 응답 서명만 붙는다."""
    source = await open_checking(client, user, balance=100_000)
    hub.hub_key = HUB_PRIVATE  # 허브는 모드와 상관없이 응답에 서명한다. hmac 모드는 보지 않는다
    hub.reply_key = OTHER_PRIVATE
    res = await send(client, user, source["account_id"], "110-123-0001")
    assert res.json()["data"]["status"] == "COMPLETED"
    assert all("x-signature-alg" not in headers for headers, _ in hub.transfer_raw)
    _, reply = await evidence(res.json()["data"]["transfer_id"])
    assert reply.signature_valid is None  # 검증하지 않음

    plain = await hub_call(client, "POST", "/interbank/inquiry", {"account_num": source["account_num"]})
    assert plain.status_code == 200 and "x-response-signature" not in plain.headers  # 키가 없으면 예전과 같다
    monkeypatch.setattr(get_settings(), "hub_public_key", HUB_PUBLIC)
    ed_res, _, _ = await hub_call_ed25519(client, "POST", "/interbank/inquiry", {"account_num": source["account_num"]})
    assert ed_res.status_code == 401 and ed_res.json()["error"] == "SIGNATURE_INVALID"

    monkeypatch.setattr(get_settings(), "interbank_signing_key", SecretStr(BANK_PRIVATE))
    signed = await hub_call(client, "POST", "/interbank/inquiry", {"account_num": source["account_num"]})
    assert signed.json() == plain.json()
    assert_reply_signed_by_us(signed, signed.request.headers["x-signature"])


async def test_5xx_is_not_signed(client, user, ed25519, monkeypatch):
    """5xx는 본문 보장이 없어 서명하지 않는다 (SPEC 2.5). 허브는 그대로 재시도한다."""
    from avengers_bank.domains.interbank import service

    async def broken(db, data):
        raise RuntimeError("DB 끊김")

    monkeypatch.setattr(service, "receive", broken)
    account = await open_checking(client, user)
    res, _, _ = await hub_call_ed25519(client, "POST", "/interbank/receive", receive_payload(account["account_num"]))
    assert res.status_code == 500 and "x-response-signature" not in res.headers
    [request_row] = await evidence(receive_payload("x")["transfer_id"])  # 요청은 처리 전에 남는다
    assert request_row.direction == "RECEIVE_IN"


async def test_prod_mount_path_is_signed(client, user, ed25519):
    """운영(/api 아래 마운트)에서도 /api/interbank/* 응답에 서명하고, 서명 경로는 /interbank 뒤의 부분이다."""
    from httpx import ASGITransport, AsyncClient

    from avengers_bank.prod import app as prod_app

    account = await open_checking(client, user)
    async with AsyncClient(transport=ASGITransport(app=prod_app), base_url="http://test") as prod:
        res, headers, _ = await hub_call_ed25519(prod, "POST", "/api/interbank/inquiry", {"account_num": account["account_num"]})
    assert res.status_code == 200, res.text
    assert_reply_signed_by_us(res, headers["X-Signature"])
    assert "x-response-signature" not in (await client.get("/health")).headers  # /interbank 밖은 그대로


# ── 키 도구 (keys.py) ───────────────────────────────────────────

async def test_keys_generate(capsys):
    assert await keys.run(["generate"]) == 0
    out = capsys.readouterr().out
    private = out.split("INTERBANK_SIGNING_KEY, 서버 .env에만): ")[1].split()[0]
    public = out.split("비밀 아님):")[1].split()[0]
    assert public_key_of(private) == public and fingerprint(public) in out


async def test_keys_register_status_and_hub_key(client, hub, monkeypatch, capsys):
    """register: 설정의 개인키에서 공개키를 만들어 HMAC으로 서명한 PUT /v1/keys (hmac 모드 = 처음 등록)."""
    monkeypatch.setattr(get_settings(), "interbank_signing_key", SecretStr(BANK_PRIVATE))
    hub.hub_key = HUB_PRIVATE
    assert await keys.run(["register"]) == 0
    assert hub.bank_public_key == BANK_PUBLIC
    assert hub.algs[-1] == ("/v1/keys", "hmac")
    assert f"등록됨: 지문 {fingerprint(BANK_PUBLIC)}" in capsys.readouterr().out

    assert await keys.run(["status"]) == 0
    out = capsys.readouterr().out
    assert f"fingerprint: {fingerprint(BANK_PUBLIC)}" in out and "signature_mode: hmac" in out

    assert await keys.run(["hub-key"]) == 0
    out = capsys.readouterr().out
    assert HUB_PUBLIC in out and fingerprint(HUB_PUBLIC) in out

    hub.hub_key = None
    assert await keys.run(["hub-key"]) == 1  # 허브가 아직 키가 없음 (404 HUB_KEY_MISSING)


async def test_keys_rotate_in_ed25519_mode(client, ed25519, capsys):
    """회전: 새 공개키를 지금(옛) 키의 Ed25519 서명으로 등록한다 (SPEC 2.6)."""
    _, new_public = generate_keypair()
    assert await keys.run(["register", "--public-key", new_public]) == 0
    assert ed25519.algs[-1] == ("/v1/keys", "ed25519") and ed25519.bank_public_key == new_public
    out = capsys.readouterr().out
    assert f"이전 키 {fingerprint(BANK_PUBLIC)}" in out
    assert await keys.run(["register", "--public-key", "short"]) == 2


async def test_evidence_table_is_append_only_rows(client, user, hub):
    """hmac 모드에서도 이체 원문은 남는다 (서명 없는 응답은 signature_alg NULL). 결과 조회·조회 API는 남기지 않는다."""
    source = await open_checking(client, user, balance=100_000)
    tid = (await send(client, user, source["account_id"], "110-123-0001")).json()["data"]["transfer_id"]
    async with SessionLocal() as db, db.begin():
        rows = list(await db.scalars(select(HubEvidence)))
    assert [(r.transfer_id, r.direction, r.signature_alg) for r in rows] == [
        (tid, "TRANSFER_OUT", "hmac"), (tid, "TRANSFER_REPLY", None)]
