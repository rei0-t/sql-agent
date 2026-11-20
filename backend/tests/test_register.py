"""注册与多租户隔离：新用户必须看不到别人的东西。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _register(client: TestClient, username: str, password: str = "passw0rd-123"):
    return client.post("/api/v1/auth/register", json={"username": username, "password": password})


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_auth_config_is_public(client: TestClient) -> None:
    response = client.get("/api/v1/auth/config")
    assert response.status_code == 200
    assert "allow_registration" in response.json()


def test_register_creates_own_workspace(client: TestClient) -> None:
    username = _unique("newbie")
    created = _register(client, username)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["access_token"]
    assert body["user"]["username"] == username

    workspace_id = body["user"]["workspace_id"]
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["workspace_id"] == workspace_id

    # 新用户的数据源列表是空的，看不到别人的库
    datasources = client.get("/api/v1/datasources", headers=headers)
    assert datasources.status_code == 200
    assert datasources.json() == []

    # 新用户的模型配置也独立：未配置
    setting = client.get("/api/v1/settings/llm", headers=headers)
    assert setting.status_code == 200
    assert setting.json()["source"] in ("env", "none")


def test_two_users_do_not_share_datasources(
    client: TestClient, admin_headers: dict[str, str], sqlite_datasource: dict
) -> None:
    username = _unique("isolation")
    token = _register(client, username).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 新用户看不到 admin 的演示库
    visible = client.get("/api/v1/datasources", headers=headers).json()
    assert all(item["id"] != sqlite_datasource["id"] for item in visible)

    # 也不能按 id 直接读结构
    peek = client.get(f"/api/v1/datasources/{sqlite_datasource['id']}/schema", headers=headers)
    assert peek.status_code == 404


def test_duplicate_username_is_rejected(client: TestClient) -> None:
    username = _unique("dup")
    assert _register(client, username).status_code == 201
    again = _register(client, username)
    assert again.status_code == 409
    assert "占用" in again.json()["detail"]


def test_weak_or_bad_inputs_rejected(client: TestClient) -> None:
    short_password = client.post(
        "/api/v1/auth/register", json={"username": _unique("shortpw"), "password": "1234567"}
    )
    assert short_password.status_code == 422

    bad_name = client.post(
        "/api/v1/auth/register", json={"username": "带中文的名字", "password": "passw0rd-123"}
    )
    assert bad_name.status_code == 400


def test_registered_user_can_login_later(client: TestClient) -> None:
    username = _unique("relogin")
    password = "passw0rd-123"
    assert _register(client, username, password).status_code == 201

    login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200
    assert login.json()["user"]["username"] == username

    wrong = client.post("/api/v1/auth/login", json={"username": username, "password": "nope-nope"})
    assert wrong.status_code == 401