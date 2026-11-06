"""Ed25519 키 관리 도구 (SPEC 2.6). 전환 순서는 docs/INTERBANK.md "부인방지(Ed25519)".

    uv run python -m avengers_bank.domains.interbank.keys generate
        키 쌍을 만들어 개인키·공개키·지문을 출력한다. 개인키는 서버 .env의 INTERBANK_SIGNING_KEY에만 넣는다
    uv run python -m avengers_bank.domains.interbank.keys register [--public-key <공개키>]
        INTERBANK_SIGNING_KEY의 공개키를 허브에 등록한다 (PUT /v1/keys). 지금 인증으로 서명한다:
        hmac·both 모드는 HMAC, ed25519 모드는 지금 키. 키를 바꿀 때(회전)는 .env를 옛 키로 둔 채
        --public-key에 새 공개키를 주고 부른 뒤, 24시간 안에 .env를 새 개인키로 바꿔 재시작한다
    uv run python -m avengers_bank.domains.interbank.keys status
        허브에 등록된 내 키 상태 (GET /v1/keys: 지문, 모드, 이전 키 만료)
    uv run python -m avengers_bank.domains.interbank.keys hub-key
        허브 공개키와 지문 (GET /v1/hub-key). 허브 관리자가 따로 알려 준 지문과 같을 때만 HUB_PUBLIC_KEY에 넣는다

개인키는 출력 외에 어디에도 저장하지 않는다 (generate). 출력한 터미널 기록은 지운다.
"""

import argparse
import asyncio
import sys

from avengers_bank.core.config import get_settings
from avengers_bank.domains.interbank.hub_client import HubReply, hub_client
from avengers_bank.domains.interbank.signing import fingerprint, generate_keypair, is_valid_key, public_key_of


def _print_reply(reply: HubReply) -> None:
    if reply.status is None:
        print("허브 응답 없음 (주소·네트워크, ed25519 모드면 허브 응답 서명과 HUB_PUBLIC_KEY를 확인하세요)")
    else:
        print(f"허브 HTTP {reply.status}: {reply.error} {reply.message}".rstrip())


def cmd_generate() -> int:
    private, public = generate_keypair()
    print(f"개인키 (INTERBANK_SIGNING_KEY, 서버 .env에만): {private}")
    print(f"공개키 (허브에 등록, 비밀 아님):                {public}")
    print(f"지문:                                          {fingerprint(public)}")
    print("개인키는 허브를 포함해 누구에게도 주지 않습니다. .env에 넣은 뒤 register로 공개키를 등록하세요.")
    return 0


def _require_hub() -> bool:
    settings = get_settings()
    if not settings.interbank_enabled:
        print("HUB_URL·HUB_API_KEY·HUB_SECRET이 설정되지 않았습니다", file=sys.stderr)
        return False
    return True


async def cmd_register(public_key: str | None) -> int:
    if not _require_hub():
        return 2
    settings = get_settings()
    if public_key is None:
        if settings.interbank_signing_key is None:
            print("INTERBANK_SIGNING_KEY가 없습니다. generate로 만든 개인키를 .env에 넣거나 --public-key를 주세요",
                  file=sys.stderr)
            return 2
        public_key = public_key_of(settings.interbank_signing_key.get_secret_value())
    if not is_valid_key(public_key):
        print("공개키는 raw 32바이트의 base64(44자)여야 합니다", file=sys.stderr)
        return 2
    reply = await hub_client.register_key(public_key)
    if not reply.ok:
        _print_reply(reply)
        return 1
    ours, theirs = fingerprint(public_key), reply.body.get("fingerprint")
    print(f"등록됨: 지문 {theirs} (보낸 공개키의 지문 {ours}), 모드 {reply.body.get('signature_mode')}")
    if reply.body.get("previous_fingerprint"):
        print(f"이전 키 {reply.body['previous_fingerprint']}는 {reply.body.get('previous_key_expires_at')}까지 받아 줍니다. "
              "그 전에 .env를 새 개인키로 바꿔 재시작하세요")
    if theirs != ours:
        print("허브가 돌려준 지문이 다릅니다. 허브 관리자에게 확인하세요", file=sys.stderr)
        return 1
    return 0


async def cmd_status() -> int:
    if not _require_hub():
        return 2
    reply = await hub_client.key_status()
    if not reply.ok:
        _print_reply(reply)
        return 1
    for name in ("bank_code", "fingerprint", "signature_mode", "registered_at", "previous_fingerprint",
                 "previous_key_expires_at", "hub_fingerprint"):
        print(f"{name}: {reply.body.get(name)}")
    settings = get_settings()
    if settings.interbank_signing_key is not None:
        print(f"우리 INTERBANK_SIGNING_KEY의 지문: {fingerprint(public_key_of(settings.interbank_signing_key.get_secret_value()))}")
    print(f"우리 INTERBANK_SIGNATURE_MODE: {settings.interbank_signature_mode} (허브 signature_mode와 같아야 합니다)")
    return 0


async def cmd_hub_key() -> int:
    if not get_settings().hub_url:
        print("HUB_URL이 설정되지 않았습니다", file=sys.stderr)
        return 2
    reply = await hub_client.hub_key()
    public_key = reply.body.get("public_key")
    if not reply.ok or not is_valid_key(public_key):
        _print_reply(reply)
        return 1
    print(f"허브 공개키: {public_key}")
    print(f"지문:        {fingerprint(public_key)} (허브가 알려 준 값 {reply.body.get('fingerprint')})")
    print("허브 관리자가 따로(채팅·문서가 아닌 개별 경로로) 알려 준 지문과 같을 때만 .env의 HUB_PUBLIC_KEY에 넣으세요.")
    return 0


async def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m avengers_bank.domains.interbank.keys",
                                     description="ClearingHub Ed25519 키 관리 (SPEC 2.6)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="키 쌍 생성")
    register = sub.add_parser("register", help="공개키 등록·교체 (PUT /v1/keys)")
    register.add_argument("--public-key", help="등록할 공개키 (키 회전 때 새 공개키). 없으면 INTERBANK_SIGNING_KEY의 공개키")
    sub.add_parser("status", help="내 키 등록 상태 (GET /v1/keys)")
    sub.add_parser("hub-key", help="허브 공개키와 지문 (GET /v1/hub-key)")
    args = parser.parse_args(argv)
    if args.command == "generate":
        return cmd_generate()
    if args.command == "register":
        return await cmd_register(args.public_key)
    if args.command == "status":
        return await cmd_status()
    return await cmd_hub_key()


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
