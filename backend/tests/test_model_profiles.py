"""多档模型配置：平台额度不外泄端点，自建档位按 BYOK 处理。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings

SECRET = "sk-profile-should-never-leak-987654"


@pytest.fixture(autouse=True)
def _cleanup(client: TestClient, admin_headers: dict[str, str]):
    """本模块建的档位用完就删，避免污染后面的用例。"""
    yield
    listing = client.get("/api/v1/settings/models", headers=admin_headers)
    if listing.status_code != 200:
        return
    for item in listing.json()["items"]:
        client.delete(f"/api/v1/settings/models/{item['id']}", headers=admin_headers)


def _create(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    payload = {
        "label": "本地 Ollama",
        "base_url": "https://api.example.com/v1",
        "model": "qwen-plus",
        "api_key": SECRET,
    }
    payload.update(overrides)
    response = client.post("/api/v1/settings/models", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_list(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = _create(client, admin_headers)
    assert created["label"] == "本地 Ollama"
    assert created["base_url"] == "https://api.example.com/v1"
    assert created["model"] == "qwen-plus"
    # Key 只回显掩码
    assert SECRET not in str(created)
    assert created["api_key_masked"].endswith(SECRET[-4:])

    listing = client.get("/api/v1/settings/models", headers=admin_headers)
    assert listing.status_code == 200
    body = listing.json()
    assert len(body["items"]) == 1
    assert SECRET not in str(body)


def test_platform_entry_hides_endpoint(client: TestClient, admin_headers: dict[str, str]) -> None:
    """平台额度这一档只说明可用性与剩余次数，不暴露站点端点与模型名。"""
    client.get("/api/v1/settings/models", headers=admin_headers)
    platform = client.get("/api/v1/settings/models", headers=admin_headers).json()["platform"]
    assert platform["kind"] == "platform"
    assert "base_url" not in platform
    assert "model" not in platform
    assert settings.llm_base_url not in str(platform)


def test_trial_user_cannot_see_site_config(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """没有自己档位的用户：/settings/llm 不回传站点 base_url 与模型名。"""
    client.post(
        "/api/v1/auth/register",
        json={"username": "trial-user", "password": "trial-passw0rd"},
    )
    login = client.post(
        "/api/v1/auth/login", json={"username": "trial-user", "password": "trial-passw0rd"}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {client.cookies.get('sa_session')}"}

    me = client.get("/api/v1/settings/llm", headers=headers)
    assert me.status_code == 200
    body = me.json()
    assert body["base_url"] == ""
    assert body["model"] == ""
    assert settings.llm_base_url not in str(body)


def test_chat_config_labels_platform(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    body = client.get("/api/v1/chat/config", headers=admin_headers).json()
    assert "model_label" in body
    assert "quota_total" in body
    if body["using_platform"]:
        assert body["model_label"] == "平台额度（试用）"


def test_delete_profile(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = _create(client, admin_headers, label="删掉我")
    response = client.delete(f"/api/v1/settings/models/{created['id']}", headers=admin_headers)
    assert response.status_code == 204
    listing = client.get("/api/v1/settings/models", headers=admin_headers).json()
    assert all(item["id"] != created["id"] for item in listing["items"])


def test_cannot_delete_other_workspace_profile(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    created = _create(client, admin_headers, label="别人的")

    client.post(
        "/api/v1/auth/register",
        json={"username": "other-user", "password": "other-passw0rd"},
    )
    client.post(
        "/api/v1/auth/login", json={"username": "other-user", "password": "other-passw0rd"}
    )
    headers = {"Authorization": f"Bearer {client.cookies.get('sa_session')}"}
    response = client.delete(f"/api/v1/settings/models/{created['id']}", headers=headers)
    assert response.status_code == 404


def test_rejects_private_endpoint(client: TestClient, admin_headers: dict[str, str]) -> None:
    """BYOK 的 SSRF 面：不允许把端点指到内网。"""
    response = client.post(
        "/api/v1/settings/models",
        headers=admin_headers,
        json={
            "label": "内网",
            "base_url": "http://169.254.169.254/latest",
            "model": "m",
            "api_key": "sk-x",
        },
    )
    assert response.status_code == 400