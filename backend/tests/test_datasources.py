"""数据源 CRUD、连通性测试、结构快照。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_create_test_schema_delete_flow(
    client: TestClient, admin_headers: dict[str, str], sqlite_datasource: dict
) -> None:
    ds = sqlite_datasource
    assert ds["type"] == "sqlite"
    assert ds["safety_level"] == "L0"
    assert ds["has_write_credential"] is False
    assert "password" not in ds

    listed = client.get("/api/v1/datasources", headers=admin_headers)
    assert listed.status_code == 200
    assert any(item["id"] == ds["id"] for item in listed.json())

    tested = client.post(f"/api/v1/datasources/{ds['id']}/test", headers=admin_headers)
    assert tested.status_code == 200, tested.text
    body = tested.json()
    assert body["ok"] is True
    assert body["server_version"].startswith("SQLite")

    schema = client.get(f"/api/v1/datasources/{ds['id']}/schema", headers=admin_headers)
    assert schema.status_code == 200, schema.text
    payload = schema.json()
    tables = {table["name"]: table for table in payload["tables"]}
    assert set(tables) == {"customers", "orders"}

    orders = tables["orders"]
    columns = {column["name"]: column for column in orders["columns"]}
    assert columns["id"]["primary_key"] is True
    assert columns["amount"]["primary_key"] is False
    assert orders["row_count_estimate"] == 2
    # 对外契约字段名是 schema（不是 schema_name）
    assert "schema" in orders
    assert "schema_name" not in orders


def test_schema_missing_datasource(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    assert client.get("/api/v1/datasources/999999/schema", headers=admin_headers).status_code == 404


def test_delete_is_idempotent_enough(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path
) -> None:
    created = client.post(
        "/api/v1/datasources",
        headers=admin_headers,
        json={"name": "待删除", "type": "sqlite", "database": str(demo_sqlite)},
    )
    assert created.status_code == 201
    ds_id = created.json()["id"]

    assert client.delete(f"/api/v1/datasources/{ds_id}", headers=admin_headers).status_code == 204
    assert client.delete(f"/api/v1/datasources/{ds_id}", headers=admin_headers).status_code == 404


def test_safety_level_requires_separate_credentials(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path
) -> None:
    """L2 及以上必须提供独立的可写账号——这是双通道的底线，不允许只给一个口令。"""
    rejected = client.post(
        "/api/v1/datasources",
        headers=admin_headers,
        json={
            "name": "只给了一个口令",
            "type": "sqlite",
            "database": str(demo_sqlite),
            "safety_level": "L2",
        },
    )
    assert rejected.status_code == 422
    assert "独立的可写账号" in str(rejected.json())

    accepted = client.post(
        "/api/v1/datasources",
        headers=admin_headers,
        json={
            "name": "双凭证",
            "type": "sqlite",
            "database": str(demo_sqlite),
            "safety_level": "L2",
            "writable_username": "writer",
            "writable_password": "writer-password",
        },
    )
    assert accepted.status_code == 201
    body = accepted.json()
    assert body["has_write_credential"] is True
    assert body["safety_level"] == "L2"
    client.delete(f"/api/v1/datasources/{body['id']}", headers=admin_headers)


def test_mysql_requires_host_and_port(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/datasources",
        headers=admin_headers,
        json={"name": "缺字段", "type": "mysql", "database": "demo", "username": "root"},
    )
    assert response.status_code == 422

def test_delete_invalidates_schema_cache(
    client: TestClient, admin_headers: dict[str, str], monkeypatch
) -> None:
    """回归：删掉数据源要清缓存，否则 SQLite 复用 rowid 时会读到旧表结构。"""
    from app.api import datasources as datasources_api

    calls: list[int] = []
    monkeypatch.setattr(datasources_api, "invalidate_cache", lambda ds_id=None: calls.append(ds_id))

    created = client.post(
        "/api/v1/datasources",
        headers=admin_headers,
        json={"name": "缓存测试", "type": "sqlite", "database": "unused.db"},
    )
    ds_id = created.json()["id"]
    assert client.delete(f"/api/v1/datasources/{ds_id}", headers=admin_headers).status_code == 204
    assert calls == [ds_id]
