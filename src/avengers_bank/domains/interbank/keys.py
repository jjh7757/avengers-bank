"""ClearingHub 등록·Ed25519 키 관리 도구 (SPEC 2.6·3.5·3.6). 설정 순서는 docs/INTERBANK.md "부인방지(Ed25519)".

    uv run python -m avengers_bank.domains.interbank.keys generate
        키 쌍을 만들어 개인키·공개키·지문을 출력한다. 개인키는 서버 .env의 INTERBANK_SIGNING_KEY에만 넣는다
    uv run python -m avengers_bank.domains.interbank.keys hub-key
        허브 공개키와 지문 (GET /v1/hub-key). 허브 관리자가 따로 알려 준 지문과 같을 때만 HUB_PUBLIC_KEY에 넣는다
    uv run python -m avengers_bank.domains.interbank.keys register-bank --invite-code <코드> --name <이름> --base-url <주소>
        셀프 등록 (POST /v1/banks/register, 인증 없음). INTERBANK_SIGNING_KEY의 공개키로 등록하고
        bank_code·api_key·hub_fingerprint·ping을 출력한다. 새 환경(다른 팀, 재배포)에서 한 번만 쓴다
    uv run python -m avengers_bank.domains.interbank.keys ping
        허브가 우리 base_url을 불러 본 결과 (POST /v1/me/ping)
    uv run python -m avengers_bank.domains.interbank.keys status
        허브에 등록된 내 정보와 키 상태 (GET /v1/me + GET /v1/keys)
    uv run python -m avengers_bank.domains.interbank.keys register [--public-key <공개키>]
        공개키 교체 (PUT /v1/keys). 지금 INTERBANK_SIGNING_KEY로 서명한다. 회전은 .env를 옛 키로 둔 채
        --public-key에 새 공개키를 주고 부른 뒤, 24시간 안에 .env를 새 개인키로 바꿔 재시작한다

개인키는 출력 외에 어디에도 저장하지 않는다 (generate). register-bank의 api_key도 출력뿐이다. 출력한 터미널 기록은 지운다.
"""

import argparse
import asyncio
import json
import sys

from avengers_bank.core.config import get_settings
from avengers_bank.domains.interbank.hub_client import HubReply, hub_client
from avengers_bank.domains.interbank.signing import fingerprint, generate_keypair, is_valid_key, public_key_of

_ALL = ("HUB_URL", "HUB_API_KEY", "INTERBANK_SIGNING_KEY", "HUB_PUBLIC_KEY")  # 등록된 은행이 서명해 부를 때 필요한 것

def _print_reply(reply: HubReply) -> None:
    if reply.status is None:
        print("허브 응답 없음 (주소·네트워크, 또는 허브 응답 서명이 틀림 — HUB_PUBLIC_KEY를 확인하세요)")
    else:
        print(f"허브 HTTP {reply.status}: {reply.error} {reply.message}".rstrip())


def _our_public_key() -> str | None:
    key = get_settings().interbank_signing_key
    return public_key_of(key.get_secret_value()) if key else None


def _require(*names: str) -> bool:
    """필요한 설정이 다 있는지. 없으면 이름을 알려 주고 False."""
    missing = [name for name in names if name in get_settings().interbank_missing]
    if missing:
        print(f"설정이 비어 있습니다: {', '.join(missing)} (.env, docs/INTERBANK.md)", file=sys.stderr)
        return False
    return True


def _print_ping(ping: dict) -> bool:
    """ping 결과(SPEC 3.6)를 출력하고 ok인지 돌려준다."""
    for name in ("ok", "reachable", "status", "response_signature_valid"):
        print(f"  {name}: {ping.get(name)}")
    print(f"  body: {json.dumps(ping.get('body'), ensure_ascii=False)}")
    if ping.get("ok") is True:
        return True
    if not ping.get("reachable"):
        print("  → 허브가 우리 base_url에 닿지 못했습니다: 주소·방화벽·인증서·5초 타임아웃 확인")
    elif ping.get("status") in (401, 403):
        print("  → 우리가 허브 서명을 거절했습니다: HUB_PUBLIC_KEY와 base_url(경로)을 확인")
    elif ping.get("response_signature_valid") is False:
        print("  → 우리 응답 서명이 허브에 등록된 공개키와 맞지 않습니다: INTERBANK_SIGNING_KEY와 등록 지문 확인")
    else:
        print("  → SPEC 3.6의 ping 결과 표를 보고 고친 뒤 ping으로 다시 확인하세요")
    return False


def cmd_generate() -> int:
    private, public = generate_keypair()
    print(f"개인키 (INTERBANK_SIGNING_KEY, 서버 .env에만): {private}")
    print(f"공개키 (허브에 등록, 비밀 아님):                {public}")
    print(f"지문:                                          {fingerprint(public)}")
    print("개인키는 허브를 포함해 누구에게도 주지 않습니다. .env에 넣은 뒤 register-bank(새 등록)나 "
          "관리자 등록으로 공개키를 허브에 올리세요.")
    return 0


async def cmd_hub_key() -> int:
    if not _require("HUB_URL"):
        return 2
    reply = await hub_client.hub_key()
    public_key = reply.body.get("public_key")
    if not reply.ok or not is_valid_key(public_key):
        _print_reply(reply)
        return 1
    print(f"허브 공개키: {public_key}")
    print(f"지문:        {fingerprint(public_key)} (허브가 알려 준 값 {reply.body.get('fingerprint')})")
    print("허브 관리자가 따로(채팅·문서가 아닌 개별 경로로) 알려 준 지문과 같을 때만 .env의 HUB_PUBLIC_KEY에 넣으세요.")
    configured = get_settings().hub_public_key
    if configured and configured != public_key:
        print(f"지금 HUB_PUBLIC_KEY({fingerprint(configured)})와 다릅니다. 허브 관리자에게 확인하세요", file=sys.stderr)
        return 1
    return 0


async def cmd_register_bank(invite_code: str, name: str, base_url: str) -> int:
    """셀프 등록 (SPEC 3.5). HUB_API_KEY는 아직 없어도 된다 (이 응답으로 받는다)."""
    if not _require("HUB_URL", "INTERBANK_SIGNING_KEY", "HUB_PUBLIC_KEY"):
        return 2
    settings = get_settings()
    public_key = _our_public_key()
    reply = await hub_client.register_bank(invite_code, name, base_url.rstrip("/"), public_key)
    if reply.status != 201:
        _print_reply(reply)
        if reply.error == "INVITE_INVALID":
            print("초대 코드가 없거나 만료됐거나 이미 쓰였습니다. 허브 관리자에게 새 코드를 요청하세요", file=sys.stderr)
        return 1
    body = reply.body
    ok = True
    print(f"등록됨: bank_code {body.get('bank_code')}, 이름 {body.get('name')}, 순채무한도 {body.get('net_debit_cap')}")
    print(f"api_key: {body.get('api_key')}  (이 응답에만 있습니다)")
    print(f"우리 공개키 지문: {fingerprint(public_key)}")
    hub_fp, ours = body.get("hub_fingerprint"), fingerprint(settings.hub_public_key)
    print(f"hub_fingerprint: {hub_fp} (우리 HUB_PUBLIC_KEY의 지문 {ours})")
    if reply.signature_valid is not True:
        print("경고: 이 응답의 허브 서명이 HUB_PUBLIC_KEY로 검증되지 않습니다. 진짜 허브의 응답인지 알 수 없습니다. "
              "값을 쓰기 전에 허브 관리자에게 bank_code와 등록 여부를 확인하세요", file=sys.stderr)
        ok = False
    if hub_fp != ours:
        print("경고: hub_fingerprint가 HUB_PUBLIC_KEY와 다릅니다. 허브 관리자에게 지문을 다시 확인하세요", file=sys.stderr)
        ok = False
    print("ping (허브가 우리 base_url을 불러 본 결과):")
    if not _print_ping(body.get("ping") or {}):
        print("  등록은 유지됩니다. 고친 뒤 .env를 채우고 `keys ping`으로 다시 확인하세요")
        ok = False
    print(f"다음: .env의 BANK_CODE={body.get('bank_code')}, HUB_API_KEY=<위 api_key>로 넣고 재시작하세요. "
          "hub_fingerprint가 허브 관리자가 알려 준 지문과 같은지 확인하세요. 이 출력의 터미널 기록은 지우세요.")
    return 0 if ok else 1


async def cmd_ping() -> int:
    if not _require(*_ALL):
        return 2
    reply = await hub_client.ping_me()
    if not reply.ok:
        _print_reply(reply)
        return 1
    print("ping (허브가 우리 base_url을 불러 본 결과):")
    return 0 if _print_ping(reply.body) else 1


async def cmd_status() -> int:
    if not _require(*_ALL):
        return 2
    me, key = await hub_client.me(), await hub_client.key_status()
    for reply in (me, key):
        if not reply.ok:
            _print_reply(reply)
            return 1
    for name in ("bank_code", "name", "base_url", "active", "net_debit_cap", "public_key_fingerprint", "created_at"):
        print(f"{name}: {me.body.get(name)}")
    for name in ("registered_at", "previous_fingerprint", "previous_key_expires_at", "hub_fingerprint"):
        print(f"{name}: {key.body.get(name)}")
    settings = get_settings()
    ours, hub = fingerprint(_our_public_key()), fingerprint(settings.hub_public_key)
    print(f"우리 INTERBANK_SIGNING_KEY의 지문: {ours}")
    print(f"우리 HUB_PUBLIC_KEY의 지문:        {hub}")
    ok = True
    if key.body.get("fingerprint") != ours:
        print("허브에 등록된 공개키가 우리 개인키와 다릅니다 (회전 중이면 24시간 안에 .env를 새 키로)", file=sys.stderr)
        ok = False
    if key.body.get("hub_fingerprint") != hub:
        print("허브가 알려 준 허브 지문이 HUB_PUBLIC_KEY와 다릅니다. 허브 관리자에게 확인하세요", file=sys.stderr)
        ok = False
    return 0 if ok else 1


async def cmd_register(public_key: str | None) -> int:
    """공개키 교체 (SPEC 2.6). 지금 키로 서명하므로 이미 등록된 은행만 부를 수 있다."""
    if not _require(*_ALL):
        return 2
    public_key = public_key or _our_public_key()
    if not is_valid_key(public_key):
        print("공개키는 raw 32바이트의 base64(44자)여야 합니다", file=sys.stderr)
        return 2
    reply = await hub_client.register_key(public_key)
    if not reply.ok:
        _print_reply(reply)
        if reply.error in ("SIGNATURE_INVALID", "UNAUTHORIZED"):
            print("지금 키가 허브에 등록돼 있지 않으면 이 명령을 쓸 수 없습니다. 처음이면 register-bank, "
                  "개인키를 잃었으면 새 공개키를 허브 관리자에게 보내 대신 등록해 달라고 하세요", file=sys.stderr)
        return 1
    ours, theirs = fingerprint(public_key), reply.body.get("fingerprint")
    print(f"등록됨: 지문 {theirs} (보낸 공개키의 지문 {ours})")
    if reply.body.get("previous_fingerprint"):
        print(f"이전 키 {reply.body['previous_fingerprint']}는 {reply.body.get('previous_key_expires_at')}까지 받아 줍니다. "
              "그 전에 .env를 새 개인키로 바꿔 재시작하세요")
    if theirs != ours:
        print("허브가 돌려준 지문이 다릅니다. 허브 관리자에게 확인하세요", file=sys.stderr)
        return 1
    return 0


async def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m avengers_bank.domains.interbank.keys",
                                     description="ClearingHub 등록·Ed25519 키 관리 (SPEC 2.6·3.5·3.6)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="키 쌍 생성")
    sub.add_parser("hub-key", help="허브 공개키와 지문 (GET /v1/hub-key)")
    register_bank = sub.add_parser("register-bank", help="초대 코드로 셀프 등록 (POST /v1/banks/register)")
    register_bank.add_argument("--invite-code", required=True, help="허브 관리자가 개별 경로로 준 초대 코드")
    register_bank.add_argument("--name", required=True, help="다른 은행 화면에 나올 은행 이름 (1~50자)")
    register_bank.add_argument("--base-url", required=True,
                               help="허브가 부를 우리 주소 (예: https://bank.example.com/api/interbank, 공개 HTTPS)")
    sub.add_parser("ping", help="허브가 우리 base_url을 불러 본 결과 (POST /v1/me/ping)")
    sub.add_parser("status", help="내 등록 정보·키 상태 (GET /v1/me, GET /v1/keys)")
    register = sub.add_parser("register", help="공개키 교체 (PUT /v1/keys, 지금 키로 서명)")
    register.add_argument("--public-key", help="새 공개키 (회전). 없으면 INTERBANK_SIGNING_KEY의 공개키")
    args = parser.parse_args(argv)
    if args.command == "generate":
        return cmd_generate()
    if args.command == "hub-key":
        return await cmd_hub_key()
    if args.command == "register-bank":
        return await cmd_register_bank(args.invite_code, args.name, args.base_url)
    if args.command == "ping":
        return await cmd_ping()
    if args.command == "status":
        return await cmd_status()
    return await cmd_register(args.public_key)


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
