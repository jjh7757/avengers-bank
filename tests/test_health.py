import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from avengers_bank.core import health
from avengers_bank.core.logging import JsonFormatter, request_id_var

pytestmark = pytest.mark.anyio


async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok"}
    assert response.headers["cache-control"] == "no-store"


async def test_health_db_down(client, monkeypatch):
    async def broken() -> None:
        raise ConnectionError("db down")

    monkeypatch.setattr(health, "check_database", broken)
    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "error"}
    assert "db down" not in response.text  # 내부 오류 내용은 응답에 넣지 않는다


async def test_request_id_generated(client):
    response = await client.get("/")
    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32  # uuid4 hex


async def test_request_id_echoed(client):
    response = await client.get("/", headers={"X-Request-ID": "abc-123.req"})
    assert response.headers["x-request-id"] == "abc-123.req"


async def test_unsafe_request_id_replaced(client):
    response = await client.get("/", headers={"X-Request-ID": 'bad id"\\injected'})
    assert response.headers["x-request-id"] != 'bad id"\\injected'
    assert len(response.headers["x-request-id"]) == 32


async def test_request_id_on_error_response(client):
    response = await client.get("/accounts")  # 로그인 없이 → 401
    assert response.status_code == 401
    assert "x-request-id" in response.headers


async def test_access_log_has_request_id(client, caplog):
    with caplog.at_level(logging.INFO, logger="avengers_bank.access"):
        response = await client.get("/", headers={"X-Request-ID": "trace-me"})
    record = next(r for r in caplog.records if r.name == "avengers_bank.access")
    assert record.status == 200
    assert record.path == "/"
    line = json.loads(JsonFormatter().format(record))
    assert line["request_id"] == "trace-me" == response.headers["x-request-id"]
    assert line["method"] == "GET"
    assert line["status"] == 200
    assert "duration_ms" in line


def test_json_formatter_inside_request():
    token = request_id_var.set("req-1")
    try:
        record = logging.makeLogRecord({"name": "x", "levelname": "INFO", "msg": "이체 %s", "args": ("완료",)})
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert line["message"] == "이체 완료"
    assert line["request_id"] == "req-1"


async def test_prod_health_and_single_request_id(client):
    """운영 진입점: /health와 /api/health 둘 다 되고, 응답의 X-Request-ID는 하나다."""
    from avengers_bank.prod import app as prod_app

    async with AsyncClient(transport=ASGITransport(app=prod_app), base_url="http://test") as ac:
        for path in ("/health", "/api/health"):
            response = await ac.get(path, headers={"X-Request-ID": "prod-1"})
            assert response.status_code == 200, path
            assert response.json()["status"] == "ok"
            assert response.headers.get_list("x-request-id") == ["prod-1"]
