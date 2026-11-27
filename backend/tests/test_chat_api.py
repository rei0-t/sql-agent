"""SSE 问答接口：不联网，用 FakeModel 跑完整链路。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.engine.llm import FakeModel
from app.main import app

PLAN = json.dumps(
    {
        "tables": ["orders"],
        "metrics": ["gmv"],
        "filters": [],
        "time_range": "",
        "clarification": "",
    },
    ensure_ascii=False,
)
SQL = json.dumps(
    {"sql": "SELECT status, COUNT(*) AS n FROM orders GROUP BY status", "explain": "按状态统计", "assumptions": []},
    ensure_ascii=False,
)


@pytest.fixture()
def fake_model(client: TestClient):
    model = FakeModel([PLAN, SQL, "已支付 1 笔，已取消 1 笔。"])
    app.state.llm = model
    yield model
    app.state.llm = None


def _stream(client: TestClient, headers: dict[str, str], ds_id: int, question: str) -> str:
    response = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"datasource_id": ds_id, "question": question},
    )
    assert response.status_code == 200, response.text
    return response.text


def test_config_reports_model(client: TestClient, admin_headers: dict[str, str], fake_model) -> None:
    response = client.get("/api/v1/chat/config", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "fake-model"
    assert body["max_rows"] > 0


def test_stream_emits_full_sequence(
    client: TestClient, admin_headers: dict[str, str], sqlite_datasource: dict, fake_model
) -> None:
    text = _stream(client, admin_headers, sqlite_datasource["id"], "订单按状态分布如何")

    assert "event: stage" in text
    assert "event: sql" in text
    assert "event: rows" in text
    assert "event: answer" in text
    assert "event: done" in text

    sql_event = [line for line in text.splitlines() if line.startswith("data:") and "SELECT" in line]
    assert sql_event
    assert "LIMIT" in sql_event[0].upper()


def test_stream_requires_auth(client: TestClient, sqlite_datasource: dict) -> None:
    client.cookies.clear()  # 不带任何凭证
    response = client.post(
        "/api/v1/chat/stream", json={"datasource_id": sqlite_datasource["id"], "question": "hi"}
    )
    assert response.status_code == 401


def test_stream_rejects_unknown_datasource(
    client: TestClient, admin_headers: dict[str, str], fake_model
) -> None:
    response = client.post(
        "/api/v1/chat/stream",
        headers=admin_headers,
        json={"datasource_id": 987654, "question": "hi"},
    )
    assert response.status_code == 404


def test_feedback_is_audited(
    client: TestClient, admin_headers: dict[str, str], sqlite_datasource: dict
) -> None:
    response = client.post(
        "/api/v1/chat/feedback",
        headers=admin_headers,
        json={
            "datasource_id": sqlite_datasource["id"],
            "question": "有多少订单",
            "correct_sql": "SELECT COUNT(*) FROM orders",
            "note": "应该排除取消单",
        },
    )
    assert response.status_code == 202