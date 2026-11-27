"""审计层：写入（自动发生在路由里）、独立事务、查询接口、多租户隔离。"""

from __future__ import annotations

import json
import sqlite3
import uuid

from fastapi.testclient import TestClient

from app.config import settings


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def _meta_conn() -> sqlite3.Connection:
    path = settings.resolved_database_url.replace("sqlite+aiosqlite:///", "")
    return sqlite3.connect(path)


def test_audit_list_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/audit").status_code == 401


def test_audit_records_and_lists(client: TestClient, admin_headers: dict[str, str]) -> None:
    # 建一个数据源，必然产生一条 datasource.create
    created = client.post(
        "/api/v1/datasources",
        headers=admin_headers,
        json={"name": _unique("审计源"), "type": "sqlite", "database": "unused.db"},
    )
    assert created.status_code == 201
    ds_id = created.json()["id"]

    page = client.get("/api/v1/audit", headers=admin_headers, params={"action": "datasource.create"})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] >= 1
    first = body["items"][0]
    assert first["action"] == "datasource.create"
    assert first["result"] == "ok"
    assert first["detail"]["name"].startswith("审计源")
    # 每条记录都带请求 id（中间件注入）
    assert first["detail"]["request_id"]

    client.delete(f"/api/v1/datasources/{ds_id}", headers=admin_headers)


def test_audit_filters_and_pagination(client: TestClient, admin_headers: dict[str, str]) -> None:
    page = client.get(
        "/api/v1/audit", headers=admin_headers, params={"limit": 2, "offset": 0}
    ).json()
    assert page["limit"] == 2
    assert len(page["items"]) <= 2

    denied = client.get("/api/v1/audit", headers=admin_headers, params={"result": "denied"}).json()
    assert all(item["result"] == "denied" for item in denied["items"])

    # 按 detail 文本搜索（比如 SQL 片段）
    searched = client.get("/api/v1/audit", headers=admin_headers, params={"q": "不存在的关键字"}).json()
    assert searched["total"] == 0


def test_audit_actions_and_summary(client: TestClient, admin_headers: dict[str, str]) -> None:
    actions = client.get("/api/v1/audit/actions", headers=admin_headers)
    assert actions.status_code == 200
    assert "auth.login" in actions.json()

    summary = client.get("/api/v1/audit/summary", headers=admin_headers, params={"days": 7})
    assert summary.status_code == 200
    buckets = summary.json()
    assert buckets and all({"action", "result", "count"} <= set(b) for b in buckets)


def test_audit_survives_failed_login(client: TestClient) -> None:
    """登录失败也要留痕：审计走独立事务，不随业务回滚。"""
    username = _unique("ghost")
    bad = client.post("/api/v1/auth/login", json={"username": username, "password": "wrong"})
    assert bad.status_code == 401

    conn = _meta_conn()
    try:
        rows = conn.execute(
            "SELECT action, result FROM audit_logs WHERE actor_name = ? ORDER BY id DESC",
            (username,),
        ).fetchall()
    finally:
        conn.close()
    assert rows and rows[0][0] == "auth.login" and rows[0][1] == "denied"


def test_audit_is_isolated_per_workspace(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    token = client.post(
        "/api/v1/auth/register",
        json={"username": _unique("auditor"), "password": "passw0rd-123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    page = client.get("/api/v1/audit", headers=headers).json()
    # 新用户只能看到自己的注册记录，看不到 admin 的任何动作
    assert all(item["action"] == "auth.register" for item in page["items"])


def test_request_id_header(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers.get("X-Request-ID")

    echoed = client.get("/api/v1/health", headers={"X-Request-ID": "trace-me-123"})
    assert echoed.headers["X-Request-ID"] == "trace-me-123"


def test_audit_detail_is_valid_json(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    conn = _meta_conn()
    try:
        raw = conn.execute(
            "SELECT detail FROM audit_logs WHERE detail IS NOT NULL ORDER BY id DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()
    for (detail,) in raw:
        assert isinstance(json.loads(detail), dict)