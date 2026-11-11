"""계좌번호 표준 모양. 우리 은행과 ClearingHub에 연동된 다른 은행 모두 3-3-6(숫자 12자리)이다."""

import re


def normalize_account_num(account_num: str) -> str:
    """하이픈 없이 쓰거나 띄어 써도 같은 계좌로 보이게 3-3-6으로 바꾼다.
    "110900000001" · "110 900 000001" → "110-900-000001". 12자리 숫자가 아니면 앞뒤 공백만 뺀다
    (가린 번호 "110-***-0001" 같은 값은 그대로 둔다)."""
    digits = re.sub(r"[\s-]", "", account_num)
    if len(digits) == 12 and digits.isdigit():
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return account_num.strip()
