"""示例库自动发放 + 问答配额。

这两个功能是给"对外开放、但用我的 Key"这个场景准备的：
- 新用户注册完立刻有一个能问的只读库
- 每个工作空间每小时能问多少条是硬上限
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.demo import DEMO_NAME
from app.engine.llm import FakeModel
from app.main import app


@pytest.fixture()
def demo_on(monkeypatch):
    monkeypatch.setattr(settings, "demo_datasource", True)


def _register(client: TestClient) -> tuple[str, dict[str, str]]:
    username = f"demo-{uuid.uuid4().hex[:6]}"
    response = client.post(
        "/api/v1/auth/register", json={"username": username, "password": "passw0rd-123"}
    )
    assert response.status_code == 201, response.text
    return username, {"Authorization": f"Bearer {response.json()['access_token']}"}


# ---------------- 示例库 ----------------


def test_register_grants_demo_datasource(client: TestClient, demo_on) -> None:
    _, headers = _register(client)
    rows = client.get("/api/v1/datasources", headers=headers).json()

    assert len(rows) == 1
    assert rows[0]["name"] == DEMO_NAME
    assert rows[0]["type"] == "sqlite"


def test_demo_datasource_is_readable(client: TestClient, demo_on) -> None:
    _, headers = _register(client)
    ds = client.get("/api/v1/datasources", headers=headers).json()[0]

    schema = client.get(f"/api/v1/datasources/{ds['id']}/schema", headers=headers)
    assert schema.status_code == 200
    tables = {t["name"] for t in schema.json()["tables"]}
    assert {"orders", "customers", "order_items"} <= tables


def test_demo_can_be_disabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "demo_datasource", False)
    _, headers = _register(client)
    assert client.get("/api/v1/datasources", headers=headers).json() == []


def test_demo_is_not_duplicated(client: TestClient, demo_on) -> None:
    """重复发放同一份示例库不应该产生第二行。"""
    from app.demo import ensure_demo_datasource

    _, headers = _register(client)
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["workspace_id"]

    # 直接再调一次（模拟启动时的补齐逻辑）
    import asyncio

    from app.db import SessionLocal

    async def again() -> None:
        async with SessionLocal() as session:
            await ensure_demo_datasource(session, me["workspace_id"])

    asyncio.run(again())
    rows = client.get("/api/v1/datasources", headers=headers).json()
    assert len(rows) == 1


# ---------------- 问答配额 ----------------


@pytest.fixture()
def fake_model(client: TestClient):
    model = FakeModel(['{"tables": ["orders"], "clarification": ""}', '{"sql": "SELECT 1 AS n"}', "1"])
    app.state.llm = model
    yield model
    app.state.llm = None


def test_chat_quota_blocks_after_limit(
    client: TestClient, monkeypatch, demo_on, fake_model
) -> None:
    monkeypatch.setattr(settings, "chat_max_per_hour", 2)
    monkeypatch.setattr(settings, "chat_ratelimit_enabled", True)

    _, headers = _register(client)
    ds = client.get("/api/v1/datasources", headers=headers).json()[0]

    for _ in range(2):
        with client.stream(
            "POST",
            "/api/v1/chat/stream",
            headers=headers,
            json={"datasource_id": ds["id"], "question": "有多少订单"},
        ) as response:
            assert response.status_code == 200
            for _line in response.iter_lines():
                pass

    blocked = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"datasource_id": ds["id"], "question": "再来一次"},
    )
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After")
    assert "上限" in blocked.json()["detail"]


def test_quota_is_per_workspace(client: TestClient, monkeypatch, demo_on, fake_model) -> None:
    monkeypatch.setattr(settings, "chat_max_per_hour", 1)
    monkeypatch.setattr(settings, "chat_ratelimit_enabled", True)

    _, first = _register(client)
    ds_a = client.get("/api/v1/datasources", headers=first).json()[0]
    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        headers=first,
        json={"datasource_id": ds_a["id"], "question": "q1"},
    ) as response:
        for _line in response.iter_lines():
            pass
    assert (
        client.post(
            "/api/v1/chat/stream", headers=first, json={"datasource_id": ds_a["id"], "question": "q2"}
        ).status_code
        == 429
    )

    # 另一个人不受影响
    _, second = _register(client)
    ds_b = client.get("/api/v1/datasources", headers=second).json()[0]
    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        headers=second,
        json={"datasource_id": ds_b["id"], "question": "q1"},
    ) as response:
        assert response.status_code == 200
        for _line in response.iter_lines():
            pass


def test_quota_can_be_disabled(client: TestClient, monkeypatch, demo_on, fake_model) -> None:
    monkeypatch.setattr(settings, "chat_max_per_hour", 1)
    monkeypatch.setattr(settings, "chat_ratelimit_enabled", False)

    _, headers = _register(client)
    ds = client.get("/api/v1/datasources", headers=headers).json()[0]
    for question in ("q1", "q2", "q3"):
        with client.stream(
            "POST",
            "/api/v1/chat/stream",
            headers=headers,
            json={"datasource_id": ds["id"], "question": question},
        ) as response:
            assert response.status_code == 200
            for _line in response.iter_lines():
                pass