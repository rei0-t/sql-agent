"""BYOK 设置：保存、掩码、回退，以及不泄露明文。"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.config import settings

SECRET = "sk-test-should-never-be-returned-123456"


def _meta_db() -> sqlite3.Connection:
    path = settings.resolved_database_url.replace("sqlite+aiosqlite:///", "")
    return sqlite3.connect(path)


def test_llm_setting_lifecycle(client: TestClient, admin_headers: dict[str, str]) -> None:
    # 初始：没有工作区配置，环境变量也没配 -> none
    initial = client.get("/api/v1/settings/llm", headers=admin_headers)
    assert initial.status_code == 200
    assert initial.json()["configured"] in (False, True)  # 取决于环境变量
    assert initial.json()["source"] in ("env", "none")

    saved = client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={
            "base_url": "https://example.com/v1/",
            "model": "qwen-plus",
            "api_key": SECRET,
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["source"] == "workspace"
    assert body["configured"] is True
    assert body["base_url"] == "https://example.com/v1"  # 去掉结尾斜杠
    assert SECRET not in str(body)
    assert body["api_key_masked"] and body["api_key_masked"].endswith(SECRET[-4:])

    # 再读一次：仍然是掩码
    again = client.get("/api/v1/settings/llm", headers=admin_headers)
    assert again.json()["source"] == "workspace"
    assert SECRET not in str(again.json())

    # 落库是密文
    conn = _meta_db()
    try:
        row = conn.execute("select api_key_enc from llm_settings limit 1").fetchone()
    finally:
        conn.close()
    assert row is not None and SECRET not in row[0]

    # 不传 api_key 只改 model：key 保持不变
    client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={"base_url": "https://example.com/v1", "model": "qwen-max"},
    )
    after = client.get("/api/v1/settings/llm", headers=admin_headers).json()
    assert after["model"] == "qwen-max"
    assert after["configured"] is True

    # 传空串清除 key -> 回退到环境变量（测试环境是否配了 env key 决定结果）
    cleared = client.put(
        "/api/v1/settings/llm",
        headers=admin_headers,
        json={"base_url": "https://example.com/v1", "model": "qwen-max", "api_key": ""},
    )
    assert cleared.json()["source"] == ("env" if settings.llm_api_key else "none")
    assert cleared.json()["configured"] is bool(settings.llm_api_key)


def test_llm_test_without_key(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/settings/llm/test",
        headers=admin_headers,
        json={"base_url": "https://example.com/v1", "model": "qwen-plus", "api_key": ""},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "API Key" in body["message"]


def test_llm_test_rejects_bad_url(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/settings/llm/test",
        headers=admin_headers,
        json={"base_url": "ftp://example.com", "model": "m", "api_key": "sk-x"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "http" in response.json()["message"]