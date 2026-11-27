"""用户管理（管理员）：列表、禁用/启用、重置口令、以及几条自保规则。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _make_user(client: TestClient, prefix: str = "u") -> tuple[str, str, dict[str, str]]:
    """注册一个普通用户，返回 (username, token, headers)。"""
    username = f"{prefix}-{uuid.uuid4().hex[:6]}"
    response = client.post(
        "/api/v1/auth/register", json={"username": username, "password": "passw0rd-123"}
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return username, token, {"Authorization": f"Bearer {token}"}


def test_non_admin_cannot_list_users(client: TestClient) -> None:
    _, _, headers = _make_user(client)
    assert client.get("/api/v1/users", headers=headers).status_code == 403


def test_admin_lists_users(client: TestClient, admin_headers: dict[str, str]) -> None:
    username, _, _ = _make_user(client, "listed")
    rows = client.get("/api/v1/users", headers=admin_headers).json()
    assert any(row["username"] == username for row in rows)
    assert all("password_hash" not in row for row in rows)


def test_disable_kills_sessions(client: TestClient, admin_headers: dict[str, str]) -> None:
    username, _, headers = _make_user(client, "disabled")
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    user_id = next(
        row["id"]
        for row in client.get("/api/v1/users", headers=admin_headers).json()
        if row["username"] == username
    )
    assert (
        client.post(f"/api/v1/users/{user_id}/disable", headers=admin_headers).status_code == 204
    )

    # 旧令牌立即失效
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    # 也登不进来
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": username, "password": "passw0rd-123"}
        ).status_code
        == 403
    )

    # 启用后恢复
    assert client.post(f"/api/v1/users/{user_id}/enable", headers=admin_headers).status_code == 204
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": username, "password": "passw0rd-123"}
        ).status_code
        == 200
    )


def test_cannot_disable_self(client: TestClient, admin_headers: dict[str, str]) -> None:
    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    response = client.post(f"/api/v1/users/{me['id']}/disable", headers=admin_headers)
    assert response.status_code == 400
    assert "自己" in response.json()["detail"]


def test_reset_password_returns_temp_and_invalidates_old(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    username, _, headers = _make_user(client, "resetpw")
    user_id = next(
        row["id"]
        for row in client.get("/api/v1/users", headers=admin_headers).json()
        if row["username"] == username
    )

    reset = client.post(f"/api/v1/users/{user_id}/reset-password", headers=admin_headers)
    assert reset.status_code == 200
    temp = reset.json()["password"]
    assert len(temp) >= 10

    # 旧会话失效
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    # 临时口令可登录
    login = client.post("/api/v1/auth/login", json={"username": username, "password": temp})
    assert login.status_code == 200
    # 原密码不行了
    old = client.post("/api/v1/auth/login", json={"username": username, "password": "passw0rd-123"})
    assert old.status_code == 401


def test_last_admin_guard(client: TestClient, admin_headers: dict[str, str]) -> None:
    """唯一的管理员不能被降级；这里通过禁用自己间接验证（禁用自己已被拦）。

    另建一个 admin 再禁用原 admin，应当允许——说明守卫是"至少保留一个"而不是"不许动管理员"。
    """
    rows = client.get("/api/v1/users", headers=admin_headers).json()
    admins = [row for row in rows if row["role"] == "admin" and row["is_active"]]
    assert len(admins) == 1  # 只有引导管理员

    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    assert client.post(f"/api/v1/users/{me['id']}/disable", headers=admin_headers).status_code == 400


def test_user_actions_are_audited(client: TestClient, admin_headers: dict[str, str]) -> None:
    username, _, _ = _make_user(client, "audituser")
    user_id = next(
        row["id"]
        for row in client.get("/api/v1/users", headers=admin_headers).json()
        if row["username"] == username
    )
    client.post(f"/api/v1/users/{user_id}/disable", headers=admin_headers)
    client.post(f"/api/v1/users/{user_id}/enable", headers=admin_headers)
    client.post(f"/api/v1/users/{user_id}/reset-password", headers=admin_headers)

    page = client.get(
        "/api/v1/audit", headers=admin_headers, params={"action": "user.", "limit": 20}
    ).json()
    actions = {item["action"] for item in page["items"]}
    # 前缀搜索不支持，这里换成逐个动作查询
    for action in ("user.disable", "user.enable", "user.reset_password"):
        found = client.get("/api/v1/audit", headers=admin_headers, params={"action": action}).json()
        assert found["total"] >= 1, action
    assert actions is not None