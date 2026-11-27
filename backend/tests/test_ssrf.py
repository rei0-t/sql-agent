"""SSRF 防护：BYOK 的 base_url 不能指向内网。

背景：用户能自己填模型端点，服务端会去请求它。没有校验的话，
「测试连接」就是一个内网探测跳板，错误信息还会回显对方响应体。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.netguard import UnsafeUrlError, check_base_url


def _put(client: TestClient, headers: dict[str, str], url: str):
    return client.put(
        "/api/v1/settings/llm",
        headers=headers,
        json={"base_url": url, "model": "qwen-plus", "api_key": ""},
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434/v1",
        "http://localhost:8080/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/v1",
        "http://192.168.1.10:8000/v1",
        "http://[::1]:8000/v1",
        "http://100.100.100.200/latest/meta-data",
        "ftp://example.com/v1",
        "file:///etc/passwd",
    ],
)
def test_private_targets_are_rejected(
    client: TestClient, admin_headers: dict[str, str], url: str
) -> None:
    response = _put(client, admin_headers, url)
    assert response.status_code == 400, f"{url} 应被拒绝"
    assert "不允许" in response.json()["detail"] or "http" in response.json()["detail"]


def test_domain_resolving_to_private_ip_is_rejected(
    client: TestClient, admin_headers: dict[str, str], monkeypatch
) -> None:
    """域名本身没问题，但解析结果落在内网——同样要拦（否则解析即可绕过）。"""
    monkeypatch.setattr("app.netguard._resolve", lambda host, port: ["10.1.2.3"])
    response = _put(client, admin_headers, "https://innocent.example.com/v1")
    assert response.status_code == 400
    assert "内网" in response.json()["detail"]


def test_public_target_is_accepted(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = _put(client, admin_headers, "https://dashscope.aliyuncs.com/compatible-mode/v1/")
    assert response.status_code == 200, response.text
    assert response.json()["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_private_allowed_when_flag_on(
    client: TestClient, admin_headers: dict[str, str], monkeypatch
) -> None:
    """本地跑 Ollama 的场景：显式打开开关就放行。"""
    monkeypatch.setattr(settings, "llm_allow_private_hosts", True)
    response = _put(client, admin_headers, "http://127.0.0.1:11434/v1")
    assert response.status_code == 200, response.text


def test_check_base_url_unit() -> None:
    with pytest.raises(UnsafeUrlError):
        check_base_url("http://127.0.0.1:11434/v1")
    with pytest.raises(UnsafeUrlError):
        check_base_url("not-a-url")
    with pytest.raises(UnsafeUrlError):
        check_base_url("https://example.com", resolver=lambda host, port: [])
    # 显式放行时不解析、不拦截
    assert check_base_url("http://localhost:11434/v1/", allow_private=True) == (
        "http://localhost:11434/v1"
    )
    # IPv4-mapped IPv6 也要识别成内网
    with pytest.raises(UnsafeUrlError):
        check_base_url("http://[::ffff:127.0.0.1]/v1")