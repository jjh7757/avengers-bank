"""거래내역의 상대방(이름·계좌·은행)과 최근 보낸 상대 (GET /transfers/recent-recipients)"""

import pytest

from tests.conftest import open_checking
from tests.test_interbank import hub, hub_call, receive_payload, send  # noqa: F401  hub는 fixture

pytestmark = pytest.mark.anyio


async def histories(client, headers, account_id: int) -> list[dict]:
    return (await client.get(f"/accounts/checking/{account_id}/histories", headers=headers)).json()["data"]


async def recent(client, headers) -> list[dict]:
    res = await client.get("/transfers/recent-recipients", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["data"]


async def local_send(client, headers, source: dict, target: dict, amount: int = 10_000):
    res = await client.post("/transfers", headers=headers, json={
        "from_checking_account_id": source["account_id"], "to_account_num": target["account_num"], "amount": amount,
    })
    assert res.status_code == 200, res.text


async def test_internal_transfer_shows_both_names(client, user, other_user):
    source = await open_checking(client, user, balance=100_000)
    target = await open_checking(client, other_user)
    await local_send(client, user, source, target)

    [sent] = await histories(client, user, source["account_id"])
    assert (sent["counterpart_name"], sent["counterpart_account"], sent["counterpart_bank"]) == (
        "브루스 배너", target["account_num"], None)
    [got] = await histories(client, other_user, target["account_id"])
    assert (got["counterpart_name"], got["counterpart_account"]) == ("토니 스타크", source["account_num"])


async def test_non_transfer_rows_have_no_counterpart(client, user):
    source = await open_checking(client, user)
    res = await client.post(f"/accounts/checking/{source['account_id']}/cash-deposit", headers=user, json={"amount": 5_000})
    assert res.status_code == 200, res.text
    rows = await histories(client, user, source["account_id"])
    assert rows and all(r["counterpart_name"] is None and r["counterpart_account"] is None for r in rows)


async def test_interbank_rows_use_hub_names(client, user, hub):
    source = await open_checking(client, user, balance=100_000)
    assert (await send(client, user, source["account_id"], "110-123-0001")).status_code == 200
    assert (await send(client, user, source["account_id"], "110-123-0007")).status_code == 400  # 거절 → 되돌림
    payload = receive_payload(source["account_num"])
    assert (await hub_call(client, "POST", "/interbank/receive", payload)).status_code == 200

    rows = {(r["type"], r["counterpart_account"]): r for r in await histories(client, user, source["account_id"])}
    out = rows[("TRANSFER_OUT", "110-123-0001")]
    assert (out["counterpart_name"], out["counterpart_bank"]) == ("김철수", "902")
    assert rows[("TRANSFER_REFUND", "110-123-0007")]["counterpart_bank"] == "902"
    got = rows[("TRANSFER_IN", "110-200-456789")]
    assert (got["counterpart_name"], got["counterpart_bank"], got["counterpart_bank_name"]) == ("김철수", "902", "SimBank")


async def test_recent_recipients_latest_first_and_unique(client, user, other_user, hub):
    source = await open_checking(client, user, balance=500_000)
    first = await open_checking(client, other_user)
    second = await open_checking(client, other_user)
    await local_send(client, user, source, first)
    assert (await send(client, user, source["account_id"], "110-123-0001")).status_code == 200
    await local_send(client, user, source, second)
    await local_send(client, user, source, first)  # 같은 상대에게 다시 → 맨 앞으로, 한 번만

    rows = await recent(client, user)
    assert [(r["to_bank"], r["account_num"]) for r in rows] == [
        (None, first["account_num"]), (None, second["account_num"]), ("902", "110-123-0001")]
    assert rows[0]["holder_name"] == "브루스 배너" and rows[2]["holder_name"] == "김철수"


async def test_recent_recipients_only_mine(client, user, other_user):
    source = await open_checking(client, user, balance=100_000)
    target = await open_checking(client, other_user)
    await local_send(client, user, source, target)
    assert await recent(client, other_user) == []  # 받기만 한 사람에게는 없다
    assert (await client.get("/transfers/recent-recipients")).status_code == 401


async def test_account_num_without_hyphens(client, user, other_user):
    """우리 계좌번호는 하이픈 없이·띄어 써도 확인·이체·수취인 등록이 된다 (저장은 원래 모양으로)"""
    source = await open_checking(client, user, balance=100_000)
    target = await open_checking(client, other_user)
    digits = target["account_num"].replace("-", "")

    res = await client.post("/transfers/inquiry", headers=user, json={"to_account_num": digits})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["holder_name"] == "브루스 배너"

    spaced = f"{digits[:3]} {digits[3:6]} {digits[6:]}"
    res = await client.post("/transfers", headers=user, json={
        "from_checking_account_id": source["account_id"], "to_account_num": spaced, "amount": 10_000,
    })
    assert res.status_code == 200, res.text
    assert res.json()["data"]["to_account_num"] == target["account_num"]
    [sent] = await histories(client, user, source["account_id"])
    assert sent["sending_account"] == target["account_num"]

    res = await client.post("/recipients", headers=user, json={"account_num": digits, "nickname": "배너"})
    assert res.status_code == 201, res.text
    assert res.json()["data"]["account_num"] == target["account_num"]
    res = await client.post("/recipients", headers=user, json={"account_num": target["account_num"], "nickname": "또"})
    assert res.status_code == 409  # 모양만 다른 같은 계좌는 중복


async def test_other_lengths_are_not_reformatted(client, user):
    res = await client.post("/transfers/inquiry", headers=user, json={"to_account_num": "11090000001"})  # 11자리
    assert res.status_code == 404
