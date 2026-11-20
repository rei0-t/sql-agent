"""开发者接口：API Key 生命周期 + /query 的 JSON 契约。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.engine.llm import FakeModel
from app.main import app

PLAN = json.dumps(
    {"tables": ["orders"], "metrics": [], "filters": [], "time_range": "", "clarification": ""},
    ensure_ascii=False,
)
SQL = json.dumps(
    {"sql": "SELECT COUNT(*) AS n FROM orders", "explain": "订单总数", "assumptions": []},
    ensure_ascii=False,
)


@pytest.fixture()
def fake_model(client: TestClient):
    model = FakeModel([PLAN, SQL, "共有 2 笔订单。"])
    app.state.llm = model
    yield model
    app.state.llm = None


@pytest.fixture()
def api_key(client: TestClient, admin_headers: dict[str, str]) -> dict[str, str]:
    created = client.post("/api/v1/keys", headers=admin_headers, json={"name": "ci"})
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["key"].startswith("sa_live_")
    yield {"Authorization": f"Bearer {payload['key']}", "key_id": str(payload["item"]["id"])}
    client.delete(f"/api/v1/keys/{payload['item']['id']}", headers=admin_headers)


def test_api_key_is_only_shown_once(
    client: TestClient, admin_headers: dict[str, str], api_key: dict[str, str]
) -> None:
    listing = client.get("/api/v1/keys", headers=admin_headers).json()
    assert listing[0]["prefix"].startswith("sa_live_")
    assert listing[0]["revoked"] is False
    # 列表里没有完整 key
    assert "key" not in listing[0]
    assert api_key["Authorization"].split(" ")[1] not in json.dumps(listing)


def test_api_key_can_list_datasources(
    client: TestClient, sqlite_datasource: dict, api_key: dict[str, str]
) -> None:
    response = client.get("/api/v1/datasources", headers=api_key)
    assert response.status_code == 200
    assert any(item["id"] == sqlite_datasource["id"] for item in response.json())


def test_query_endpoint_returns_json(
    client: TestClient, sqlite_datasource: dict, api_key: dict[str, str], fake_model
) -> None:
    response = client.post(
        "/api/v1/query",
        headers=api_key,
        json={"datasource_id": sqlite_datasource["id"], "question": "一共有多少订单"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["error"] is None
    assert "LIMIT" in body["sql"].upper()
    assert body["columns"] == ["n"]
    assert body["rows"] == [[2]]
    assert body["summary"]
    assert body["model"] == "fake-model"
    assert body["tokens"] > 0


def test_query_endpoint_rejects_bad_key(client: TestClient, sqlite_datasource: dict) -> None:
    response = client.post(
        "/api/v1/query",
        headers={"Authorization": "Bearer sa_live_not_a_real_key"},
        json={"datasource_id": sqlite_datasource["id"], "question": "x"},
    )
    assert response.status_code == 401


def test_query_endpoint_rejects_foreign_datasource(
    client: TestClient, api_key: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/query",
        headers=api_key,
        json={"datasource_id": 987654, "question": "x"},
    )
    assert response.status_code == 404


def test_revoked_key_stops_working(
    client: TestClient, admin_headers: dict[str, str], api_key: dict[str, str]
) -> None:
    revoked = client.delete(f"/api/v1/keys/{api_key['key_id']}", headers=admin_headers)
    assert revoked.status_code == 204

    response = client.get("/api/v1/datasources", headers=api_key)
    assert response.status_code == 401

    listing = client.get("/api/v1/keys", headers=admin_headers).json()
    assert any(item["revoked"] for item in listing)