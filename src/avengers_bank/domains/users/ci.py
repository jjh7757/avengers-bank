"""가상 CI (ClearingHub SPEC 9.1). 원본(생년월일·휴대폰번호)은 은행 밖으로 보내지 않고 이 값만 보낸다.

material = 이름 + "|" + 생년월일(YYYYMMDD) + "|" + 휴대폰번호(숫자만)
ci       = hex(HMAC-SHA256(CI_KEY, material))
"""

import hashlib
import hmac
import unicodedata

from avengers_bank.core.config import get_settings


def virtual_ci(ci_key: str, name: str, birth: str, phone: str) -> str:
    name = unicodedata.normalize("NFC", "".join(name.split()))
    phone = "".join(ch for ch in phone if ch.isdigit())
    return hmac.new(ci_key.encode(), f"{name}|{birth}|{phone}".encode(), hashlib.sha256).hexdigest()


def ci_of(name: str, birth_date: str | None, phone: str) -> str | None:
    """CI_KEY나 생년월일이 없으면 None (이 사람은 본인 계좌 조회에 나오지 않는다)."""
    key = get_settings().ci_key
    if key is None or not birth_date:
        return None
    return virtual_ci(key.get_secret_value(), name, birth_date, phone)
