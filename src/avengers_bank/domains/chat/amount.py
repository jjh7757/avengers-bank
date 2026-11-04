"""한국어 금액 정규화. "오만원", "5만 원", "50000원" → 50000.

에이전트(LLM)가 뽑은 금액을 이 결과와 비교해서 다르면 되묻는다 (STT 오인식·LLM 실수 방어).
"""

import re

DIGITS = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
SMALL_UNITS = {"십": 10, "백": 100, "천": 1_000}
BIG_UNITS = {"만": 10_000, "억": 100_000_000}

# 숫자·한글 숫자·단위·공백이 이어진 가장 긴 덩어리. "1억 2천만원"처럼 공백이 끼어도 한 금액으로 본다.
NUMBER_RUN = re.compile(r"[0-9.,일이삼사오육칠팔구영공십백천만억 ]+")
# "원" 없이 단위로 끝날 때("오만 보내줘") 뒤에 올 수 있는 것: 끝, 공백, 조사
UNIT_END_FOLLOWERS = set(" 을를이가은도요만")


def parse_korean_number(text: str) -> int | None:
    """숫자·한글 숫자·단위가 섞인 표현을 정수로. 해석할 수 없으면 None."""
    text = text.replace(",", "").replace(" ", "")
    if not text:
        return None
    total = section = 0.0
    current: float | None = None
    digits = ""

    def flush() -> None:
        nonlocal current, digits
        if digits:
            current = float(digits)
            digits = ""

    for ch in text:
        if ch.isdigit() or ch == ".":
            digits += ch
        elif ch in DIGITS:
            flush()
            current = DIGITS[ch]
        elif ch in SMALL_UNITS:
            flush()
            section += (current if current is not None else 1) * SMALL_UNITS[ch]
            current = None
        elif ch in BIG_UNITS:
            flush()
            section += current or 0
            total += (section or 1) * BIG_UNITS[ch]
            section, current = 0, None
        else:
            return None
    flush()
    value = total + section + (current or 0)
    return int(round(value)) if value > 0 else None


def find_amounts(text: str) -> list[int]:
    """문장에서 금액 표현을 모두 찾는다."""
    amounts = []
    for match in NUMBER_RUN.finditer(text):
        run = match.group().strip()
        # 덩어리가 공백으로 끝났으면 바로 뒤는 공백이다 ("오만 보내줘")
        after = " " if match.group().endswith(" ") else text[match.end():match.end() + 1]
        if not run:
            continue
        if after == "원":
            pass
        elif run[-1] in BIG_UNITS or run[-1] in "천":
            if after and after not in UNIT_END_FOLLOWERS:
                continue  # "만나서"의 "만"
            if all(ch in SMALL_UNITS or ch in BIG_UNITS for ch in run):
                continue  # "3천원만"의 조사 "만"처럼 단위 글자만 있는 경우
        else:
            continue  # 단위·"원"이 없는 숫자는 금액으로 보지 않는다 (계좌번호, 날짜 등)
        value = parse_korean_number(run)
        if value is not None:
            amounts.append(value)
    return amounts


def normalize_amount(text: str) -> int | None:
    """문장에 금액이 정확히 하나 있으면 그 값. 없거나 여러 개면 None."""
    amounts = find_amounts(text)
    return amounts[0] if len(set(amounts)) == 1 else None


def format_korean_amount(amount: int) -> str:
    """TTS·확인 카드용: 50000 → "5만원", 1550000 → "155만원", 55000 → "5만 5천원"."""
    if amount <= 0:
        return f"{amount:,}원"
    parts = []
    eok, rest = divmod(amount, 100_000_000)
    man, rest = divmod(rest, 10_000)
    if eok:
        parts.append(f"{eok:,}억")
    if man:
        parts.append(f"{man:,}만")
    if rest:
        parts.append(f"{rest:,}" if rest % 1000 else f"{rest // 1000}천")
    return " ".join(parts) + "원"
