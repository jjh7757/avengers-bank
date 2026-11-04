import pytest

from avengers_bank.domains.chat.amount import (
    find_amounts,
    format_korean_amount,
    normalize_amount,
    parse_korean_number,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("엄마한테 오만원 보내줘", 50_000),
        ("엄마한테 5만 원 보내줘", 50_000),
        ("50000원 보내", 50_000),
        ("50,000원", 50_000),
        ("오만 보내줘", 50_000),
        ("5만5천원", 55_000),
        ("오만 오천원", 55_000),
        ("백오십만원 이체", 1_500_000),
        ("150만원", 1_500_000),
        ("1.5만원", 15_000),
        ("삼천원만 보내", 3_000),
        ("십만원", 100_000),
        ("이십만 원", 200_000),
        ("만원", 10_000),
        ("1억 2천만원", 120_000_000),
        ("1,500,000원 보내줘", 1_500_000),
    ],
)
def test_normalize_amount(text, expected):
    assert normalize_amount(text) == expected


@pytest.mark.parametrize(
    "text",
    ["엄마한테 보내줘", "내 잔액 알려줘", "이체해줘", "만나서 얘기하자"],
)
def test_no_amount(text):
    assert normalize_amount(text) is None


def test_two_different_amounts_is_ambiguous():
    assert find_amounts("5만원 말고 10만원") == [50_000, 100_000]
    assert normalize_amount("5만원 말고 10만원") is None


def test_parse_rejects_garbage():
    assert parse_korean_number("엄마") is None


@pytest.mark.parametrize(
    ("amount", "spoken"),
    [(50_000, "5만원"), (55_000, "5만 5천원"), (1_500_000, "150만원"), (3_000, "3천원"), (12_345, "1만 2,345원")],
)
def test_format_korean_amount(amount, spoken):
    assert format_korean_amount(amount) == spoken
