"""발표 전 시연 시나리오 자동 점검 (실제 서버 + 실제 Gemini, 글자 입력).

    uv run python scripts/demo_check.py            # 서버: uv run fastapi dev, .env에 DEMO_MODE=true

시작할 때와 끝날 때 scripts/demo_seed.py로 시연 데이터를 초기화한다.
"""

import asyncio
import selectors
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
import demo_seed  # noqa: E402

BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def seed() -> None:
    if sys.platform == "win32":
        asyncio.run(demo_seed.run(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(demo_seed.run())


CONVERSATION_RULES = {"CONVERSATION_KEYWORD", "CONVERSATION_AI_SUSPICIOUS", "CONVERSATION_AI_SCAM"}


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'✅' if ok else '❌'} {name}: {detail}")


class Demo:
    def __init__(self) -> None:
        self.c = httpx.Client(base_url=BASE, timeout=120)
        token = self.c.post("/users/login", json={"login_id": "demo", "password": demo_seed.PASSWORD}).json()["data"]["access_token"]
        self.h = {"Authorization": f"Bearer {token}"}
        self.sid = ""

    def new_session(self) -> None:
        self.sid = self.c.post("/chat/sessions", headers=self.h).json()["data"]["session_id"]

    def say(self, text: str) -> dict:
        t = time.time()
        r = self.c.post(f"/chat/sessions/{self.sid}/messages", headers=self.h, json={"text": text})
        r.raise_for_status()
        reply = r.json()["data"]["assistant_message"]
        print(f"   사용자: {text}\n   에이전트 ({time.time() - t:.1f}s): {reply['content']}")
        return reply

    def approve(self, card: dict, pin: str | None = None) -> httpx.Response:
        return self.c.post("/transfers", headers=self.h, json={
            "from_checking_account_id": card["from_checking_account_id"], "to_account_num": card["to_account_num"],
            "amount": card["amount"], "session_id": self.sid, "confirmation_token": card["confirmation_token"],
            "device_fingerprint": "demo-check", "pin": pin,
        })

    def balance(self) -> int:
        accounts = self.c.get("/accounts", headers=self.h).json()["data"]
        return next(a["balance"] for a in accounts if a["nickname"] == "생활비")


def main() -> None:
    status = httpx.get(f"{BASE}/demo/status").json()["data"]
    if not status["demo_mode"]:
        raise SystemExit(".env에 DEMO_MODE=true를 넣고 서버를 다시 켜 주세요.")
    seed()
    d = Demo()

    print("\n[시나리오 1] 엄마한테 오만원 → 확인 카드 → 승인 → LOW 통과")
    d.new_session()
    card = d.say("엄마한테 오만원 보내줘")["card"]
    ok = card and card["amount"] == 50_000 and card["recipient_nickname"] == "엄마"
    r = d.approve(card)
    body = r.json()
    check("1 정상 이체", bool(ok) and r.status_code == 200 and body["data"]["risk_level"] == "LOW",
          f"{r.status_code} {body.get('data', {}).get('risk_level') or body['error']['code']}")

    print("\n[시나리오 2] 처음 보는 계좌로 150만원 → MEDIUM → PIN → 완료")
    card = d.say("110-900-222222 계좌로 150만원 보내줘")["card"]
    r = d.approve(card)
    error = r.json().get("error", {})
    rules = [h["code"] for h in (error.get("extra") or {}).get("rule_hits", [])]
    first_ok = error.get("code") in ("ADDITIONAL_AUTH_REQUIRED", "PIN_REQUIRED")
    r = d.approve(card, pin=demo_seed.PIN)
    check("2 추가 인증", first_ok and r.status_code == 200, f"처음 {error.get('code')} {rules} → PIN 후 {r.status_code}")

    print("\n[시나리오 3] 새벽 2시 + 보이스피싱 대화 + 처음 보는 계좌 + 잔액 95% → HIGH 차단")
    d.c.post("/demo/clock", json={"kst_hour": 2})
    try:
        d.new_session()
        d.say("검찰청 수사관이라는데 내 계좌가 범죄에 연루돼서 안전계좌로 옮기래")
        amount = d.balance() * 95 // 100 // 10_000 * 10_000
        card = d.say(f"110-900-333333 계좌로 {amount:,}원 보내줘")["card"]
        r = d.approve(card, pin=demo_seed.PIN)
        error = r.json().get("error", {})
        extra = error.get("extra") or {}
        rules = {h["code"] for h in extra.get("rule_hits", [])}
        expected = {"NIGHT_HIGH_AMOUNT", "NEW_RECIPIENT_HIGH_AMOUNT", "BALANCE_DRAIN"}
        check("3 차단", error.get("code") == "FDS_BLOCKED" and expected <= rules and bool(rules & CONVERSATION_RULES),
              f"{error.get('code')} 규칙 {sorted(rules)} ML {extra.get('ml_score')}")
        check("3 경고 문구", "송금을 요구하지 않습니다" in (extra.get("warning") or ""), "화면에 보여 줄 경고")
        factors = [f["label"] for f in extra.get("top_factors", [])]
        check("4 판단 근거(SHAP)", bool(factors), ", ".join(factors) or "없음")
    finally:
        d.c.post("/demo/clock", json={"kst_hour": None})

    print("\n[시나리오 3-2] 키워드 없는 가족 사칭 대화 → LLM 대화 판별이 잡음 (PIN 없이 승인 시도)")
    d.new_session()
    d.say("딸이 폰 액정이 깨져서 새 번호로 문자했는데, 급하게 30만원만 이 계좌로 보내달래")
    card = d.say("110-900-333333 계좌로 30만원 보내줘")["card"]
    r = d.approve(card)
    error = r.json().get("error", {})
    hits = (error.get("extra") or {}).get("rule_hits", [])
    ai = [h for h in hits if h["code"].startswith("CONVERSATION_AI")]
    check("3-2 LLM 대화 판별", error.get("code") in ("FDS_BLOCKED", "ADDITIONAL_AUTH_REQUIRED") and bool(ai),
          f"{error.get('code') or r.status_code} "
          + (f"{ai[0]['code']}: {ai[0].get('detail')}" if ai else f"규칙 {[h['code'] for h in hits]}"))

    print("\n[시나리오 6] 가입: 모아는 이용약관이 담긴 가입 화면만 가져오고, 동의·가입은 사용자가 화면에서")
    d.new_session()

    def cards() -> int:
        return len(d.c.get("/cards", headers=d.h).json()["data"])

    before = cards()
    reply = d.say("월급 통장에 연결해서 체크카드 하나 더 만들어줘")
    params = reply.get("screen_params") or {}
    salary = next(a for a in d.c.get("/accounts", headers=d.h).json()["data"] if a["nickname"] == "월급")
    check("6 가입 화면", reply.get("screen") == "signup" and params.get("kind") == "card" and cards() == before,
          f"화면 {reply.get('screen')} {params}, 발급 {cards() - before}장")
    check("6 연결 계좌 미리 채움", params.get("checking_account_id") == salary["account_id"], f"월급 통장 id {salary['account_id']}")
    d.say("네, 만들어 주세요")
    check("6 대화로는 발급 안 함", cards() == before, f"'네' 뒤 발급 {cards() - before}장 (약관 동의는 화면에서)")
    terms = d.c.get(f"/products/cards/{params.get('product_id', 2)}/terms", headers=d.h).json()["data"]
    r = d.c.post("/cards/debit", headers=d.h, json={"product_id": terms["product_id"], "terms_version": terms["version"],
                                                     "checking_account_id": salary["account_id"]})
    check("6 화면에서 동의 후 발급", r.status_code == 201 and cards() == before + 1, f"{r.status_code}, 약관 {terms['version']}")

    logs = d.c.get("/fds/logs", headers=d.h).json()["data"]
    check("FDS 기록", any(log["decision"] == "BLOCKED" for log in logs), f"{len(logs)}건 (대시보드 /fds)")

    print("\n시연 데이터를 다시 초기화합니다.")
    seed()
    passed = sum(ok for _, ok, _ in results)
    print(f"\n결과: {passed}/{len(results)} 통과")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
