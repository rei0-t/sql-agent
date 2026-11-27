"""登录失败限流：同一 IP / 同一用户名各一个滑动窗口。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.api.auth import reset_login_limits
from app.config import settings


def _login(client: TestClient, username: str, password: str):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_too_many_failures_are_blocked(client: TestClient) -> None:
    username = f"brute-{uuid.uuid4().hex[:6]}"
    limit = settings.login_max_failures_per_user

    for _ in range(limit):
        assert _login(client, username, "wrong-password").status_code == 401

    blocked = _login(client, username, "wrong-password")
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After")
    assert "秒后" in blocked.json()["detail"]


def test_success_resets_counter(client: TestClient) -> None:
    username = f"reset-{uuid.uuid4().hex[:6]}"
    created = client.post(
        "/api/v1/auth/register", json={"username": username, "password": "passw0rd-123"}
    )
    assert created.status_code == 201

    limit = settings.login_max_failures_per_user
    for _ in range(limit - 1):
        assert _login(client, username, "wrong").status_code == 401

    assert _login(client, username, "passw0rd-123").status_code == 200

    # 成功之后旧计数清零：还能再失败 limit 次而不会被立刻拦
    for _ in range(limit - 1):
        assert _login(client, username, "wrong").status_code == 401


def test_lockout_is_hard__correct_password_also_blocked(client: TestClient) -> None:
    """硬锁定：超限后正确密码也拒绝。

    这是防爆破的必然取舍——如果放行正确密码，攻击者就能全速继续猜。
    代价是「知道用户名的人可以锁你 N 秒」，README 的安全声明里写明了。
    """
    username = f"hardlock-{uuid.uuid4().hex[:6]}"
    client.post("/api/v1/auth/register", json={"username": username, "password": "passw0rd-123"})

    for _ in range(settings.login_max_failures_per_user):
        assert _login(client, username, "wrong").status_code == 401

    blocked = _login(client, username, "passw0rd-123")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0

    # 运维逃生口：清空计数后立刻恢复
    reset_login_limits()
    assert _login(client, username, "passw0rd-123").status_code == 200


def test_other_users_are_not_affected(client: TestClient) -> None:
    victim = f"victim-{uuid.uuid4().hex[:6]}"
    for _ in range(settings.login_max_failures_per_user):
        _login(client, victim, "wrong")
    assert _login(client, victim, "wrong").status_code == 429

    # 换一个用户名：user 窗口是独立的（IP 窗口还有余量）
    other = f"other-{uuid.uuid4().hex[:6]}"
    assert _login(client, other, "wrong").status_code == 401


def test_rate_limit_can_be_disabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "login_ratelimit_enabled", False)
    username = f"nolimit-{uuid.uuid4().hex[:6]}"
    for _ in range(settings.login_max_failures_per_user + 3):
        assert _login(client, username, "wrong").status_code == 401


def test_rate_limited_attempts_are_audited(client: TestClient, admin_headers: dict[str, str]) -> None:
    username = f"audited-{uuid.uuid4().hex[:6]}"
    for _ in range(settings.login_max_failures_per_user):
        _login(client, username, "wrong")
    assert _login(client, username, "wrong").status_code == 429

    page = client.get(
        "/api/v1/audit", headers=admin_headers, params={"action": "auth.login", "result": "denied"}
    ).json()
    reasons = {(item["detail"] or {}).get("reason") for item in page["items"]}
    assert "rate_limited" in reasons
    assert "invalid_credentials" in reasons


def test_reset_helper(client: TestClient) -> None:
    username = f"helper-{uuid.uuid4().hex[:6]}"
    for _ in range(settings.login_max_failures_per_user):
        _login(client, username, "wrong")
    assert _login(client, username, "wrong").status_code == 429

    reset_login_limits()
    assert _login(client, username, "wrong").status_code == 401