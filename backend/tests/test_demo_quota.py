"""示例库自动发放 + 每人固定提问额度。

这两个功能是给"对外开放、但用我的 Key"这个场景准备的：
- 新用户注册完立刻有一个能问的只读演示库
- 每个工作空间总共能问多少次是**持久**上限（重启不清零），管理员豁免
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.demo import DEMO_NAME
from app.engine.llm import FakeModel
from app.main import app

PLAN = '{"tables": ["orders"], "clarification": ""}'
SQL = '{"sql": "SELECT 1 AS n"}'


@pytest.fixture()
def demo_on(monkeypatch):
    monkeypatch.setattr(settings, "demo_datasource", True)


@pytest.fixture()
def fake_model(client: TestClient):
    model = FakeModel([PLAN, SQL, "1", PLAN, SQL, "1", PLAN, SQL, "1", PLAN, SQL, "1"])
    app.state.llm = model
    yield model
    app.state.llm = None


def _register(client: TestClient) -> tuple[str, dict[str, str]]:
    username = f"demo-{uuid.uuid4().hex[:6]}"
    response = client.post(
        "/api/v1/auth/register", json={"username": username, "password": "passw0rd-123"}
    )
    assert response.status_code == 201, response.text
    return username, {"Authorization": f"Bearer {response.json()['access_token']}"}


def _ask(client: TestClient, headers: dict[str, str], ds_id: int, question: str):
    return client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"datasource_id": ds_id, "question": question},
    )


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


# ---------------- 提问额度 ----------------


def test_quota_allows_then_blocks(client: TestClient, monkeypatch, demo_on, fake_model) -> None:
    monkeypatch.setattr(settings, "chat_max_questions", 2)

    _, headers = _register(client)
    ds_id = client.get("/api/v1/datasources", headers=headers).json()[0]["id"]

    for index in range(2):
        response = _ask(client, headers, ds_id, f"第 {index} 次")
        assert response.status_code == 200, response.text

    blocked = _ask(client, headers, ds_id, "第三次")
    assert blocked.status_code == 429
    assert "额度已用完" in blocked.json()["detail"]


def test_quota_counts_persistently(client: TestClient, monkeypatch, demo_on, fake_model) -> None:
    """额度落在库里：接口返回的剩余次数要逐次递减。"""
    monkeypatch.setattr(settings, "chat_max_questions", 3)

    _, headers = _register(client)
    ds_id = client.get("/api/v1/datasources", headers=headers).json()[0]["id"]

    assert client.get("/api/v1/chat/config", headers=headers).json()["remaining_questions"] == 3
    assert _ask(client, headers, ds_id, "q1").status_code == 200
    assert client.get("/api/v1/chat/config", headers=headers).json()["remaining_questions"] == 2
    assert _ask(client, headers, ds_id, "q2").status_code == 200
    assert client.get("/api/v1/chat/config", headers=headers).json()["remaining_questions"] == 1


def test_admin_is_exempt(client: TestClient, monkeypatch, admin_headers, sqlite_datasource, fake_model) -> None:
    monkeypatch.setattr(settings, "chat_max_questions", 1)
    for index in range(3):
        response = _ask(client, admin_headers, sqlite_datasource["id"], f"admin {index}")
        assert response.status_code == 200, response.text

    assert client.get("/api/v1/chat/config", headers=admin_headers).json()["remaining_questions"] is None


def test_quota_zero_means_unlimited(client: TestClient, monkeypatch, demo_on, fake_model) -> None:
    monkeypatch.setattr(settings, "chat_max_questions", 0)

    _, headers = _register(client)
    ds_id = client.get("/api/v1/datasources", headers=headers).json()[0]["id"]
    for index in range(4):
        assert _ask(client, headers, ds_id, f"q{index}").status_code == 200
    assert client.get("/api/v1/chat/config", headers=headers).json()["remaining_questions"] is None


def test_quota_is_per_workspace(client: TestClient, monkeypatch, demo_on, fake_model) -> None:
    monkeypatch.setattr(settings, "chat_max_questions", 1)

    _, first = _register(client)
    ds_a = client.get("/api/v1/datasources", headers=first).json()[0]["id"]
    assert _ask(client, first, ds_a, "a1").status_code == 200
    assert _ask(client, first, ds_a, "a2").status_code == 429

    _, second = _register(client)
    ds_b = client.get("/api/v1/datasources", headers=second).json()[0]["id"]
    assert _ask(client, second, ds_b, "b1").status_code == 200


def test_quota_exhaustion_is_audited(
    client: TestClient, monkeypatch, admin_headers, demo_on, fake_model
) -> None:
    monkeypatch.setattr(settings, "chat_max_questions", 1)

    _, headers = _register(client)
    ds_id = client.get("/api/v1/datasources", headers=headers).json()[0]["id"]
    _ask(client, headers, ds_id, "q1")
    _ask(client, headers, ds_id, "q2")  # 这里 429，审计落在该用户自己的空间

    page = client.get(
        "/api/v1/audit", headers=headers, params={"action": "chat.read", "result": "denied"}
    ).json()
    reasons = {(item["detail"] or {}).get("reason") for item in page["items"]}
    assert "quota_exhausted" in reasons


def test_byok_is_not_limited(client: TestClient, monkeypatch, demo_on, fake_model) -> None:
    """自己配了 Key 的人花的是自己的钱，不该被站点额度限制。"""
    monkeypatch.setattr(settings, "chat_max_questions", 1)

    _, headers = _register(client)
    ds_id = client.get("/api/v1/datasources", headers=headers).json()[0]["id"]

    saved = client.put(
        "/api/v1/settings/llm",
        headers=headers,
        json={
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-own-key",
        },
    )
    assert saved.status_code == 200, saved.text

    for index in range(3):
        assert _ask(client, headers, ds_id, f"q{index}").status_code == 200
    assert client.get("/api/v1/chat/config", headers=headers).json()["remaining_questions"] is None


def test_shared_key_still_limited(client: TestClient, monkeypatch, demo_on, fake_model) -> None:
    """没配 Key 的人用的是公共 Key，照常扣额度。"""
    monkeypatch.setattr(settings, "chat_max_questions", 1)

    _, headers = _register(client)
    ds_id = client.get("/api/v1/datasources", headers=headers).json()[0]["id"]
    assert _ask(client, headers, ds_id, "q1").status_code == 200
    assert _ask(client, headers, ds_id, "q2").status_code == 429