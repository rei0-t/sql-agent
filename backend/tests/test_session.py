"""会话机制：httpOnly cookie、CSRF 双提交、改密码后旧令牌失效。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _login(client: TestClient, username: str = "admin", password: str = "test-password"):
    client.cookies.clear()
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def _csrf(client: TestClient) -> str:
    value = client.cookies.get("sa_csrf")
    assert value, "登录后应当有 CSRF cookie"
    return value


# ---------------- cookie 与会话 ----------------


def test_login_sets_httponly_session_and_readable_csrf(client: TestClient) -> None:
    response = _login(client)

    assert response.status_code == 200
    session_cookie = response.headers.get("set-cookie", "")
    assert "sa_session=" in session_cookie
    assert "HttpOnly" in session_cookie

    # CSRF cookie 必须存在且不是 httpOnly（前端要读）
    assert client.cookies.get("sa_csrf")
    assert client.cookies.get("sa_session")


def test_cookie_alone_authenticates(client: TestClient) -> None:
    _login(client)
    # 不带 Authorization 头，只靠 cookie
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


def test_logout_clears_session(client: TestClient) -> None:
    _login(client)
    assert client.get("/api/v1/auth/me").status_code == 200

    out = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": _csrf(client)})
    assert out.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_requires_csrf(client: TestClient) -> None:
    """跨站 POST 一下就能把人踢下线，也是 CSRF，不能因为它不要求登录就放行。"""
    _login(client)
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


# ---------------- CSRF ----------------


def test_cookie_write_requires_csrf_header(client: TestClient) -> None:
    _login(client)
    # 有 cookie、没 CSRF 头 → 拒绝
    denied = client.put(
        "/api/v1/settings/llm", json={"base_url": "https://example.com/v1", "model": "m"}
    )
    assert denied.status_code == 403
    assert "CSRF" in denied.json()["detail"]

    ok = client.put(
        "/api/v1/settings/llm",
        json={"base_url": "https://example.com/v1", "model": "m"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert ok.status_code == 200


def test_bearer_token_does_not_need_csrf(client: TestClient, admin_headers: dict[str, str]) -> None:
    """脚本/API Key 走 Authorization 头，不受 CSRF 约束。"""
    client.cookies.clear()
    response = client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={"base_url": "https://example.com/v1", "model": "m"},
    )
    assert response.status_code == 200


# ---------------- 改密码 ----------------


def test_change_password_invalidates_old_tokens(client: TestClient) -> None:
    username = f"pw-{uuid.uuid4().hex[:6]}"
    created = client.post(
        "/api/v1/auth/register", json={"username": username, "password": "old-pass-123"}
    )
    assert created.status_code == 201
    old_token = created.json()["access_token"]

    login = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "old-pass-123"}
    )
    assert login.status_code == 200

    changed = client.post(
        "/api/v1/auth/password",
        json={"current_password": "old-pass-123", "new_password": "new-pass-456"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert changed.status_code == 204

    # 旧 token 失效
    stale = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert stale.status_code == 401

    # 新密码可登录
    again = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "new-pass-456"}
    )
    assert again.status_code == 200


def test_change_password_rejects_wrong_current(client: TestClient) -> None:
    username = f"pwbad-{uuid.uuid4().hex[:6]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "old-pass-123"})

    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": "nope", "new_password": "new-pass-456"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 400
    assert "当前密码" in response.json()["detail"]


def test_change_password_rejects_same_password(client: TestClient) -> None:
    username = f"pwsame-{uuid.uuid4().hex[:6]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "same-pass-123"})

    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": "same-pass-123", "new_password": "same-pass-123"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 400


def test_password_change_is_audited(client: TestClient) -> None:
    """审计按工作空间隔离：改密码的人自己能看到这条记录（管理员看不到别人的租户）。"""
    username = f"pwaudit-{uuid.uuid4().hex[:6]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "old-pass-123"})
    client.post(
        "/api/v1/auth/password",
        json={"current_password": "old-pass-123", "new_password": "new-pass-456"},
        headers={"X-CSRF-Token": _csrf(client)},
    )

    page = client.get(
        "/api/v1/audit", params={"action": "auth.password_change"}
    ).json()
    assert page["total"] >= 1
    assert page["items"][0]["detail"]["request_id"]