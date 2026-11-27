"""测试夹具。

注意：环境变量必须在导入 app 之前设置，因为 Settings 在模块导入时就已实例化。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest


def _fresh_dir(base: Path, prefix: str) -> Path:
    """建一个临时目录。

    刻意不用 ``tempfile.mkdtemp``：它在 Windows 上以 0o700 建目录，会生成
    受限 ACL，SQLite 随后无法在该目录里创建数据库文件。这里用默认权限建目录。
    """
    base.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        candidate = base / f"{prefix}{uuid.uuid4().hex[:10]}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError("无法创建临时目录")


_TMP = _fresh_dir(Path(tempfile.gettempdir()), "sqlagent-test-")
os.environ["SQLAGENT_DATA_DIR"] = str(_TMP)
os.environ["SQLAGENT_DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'meta.db').as_posix()}"
os.environ["SQLAGENT_SECRET_KEY"] = "test-secret-key-do-not-use-in-prod"
os.environ["SQLAGENT_ADMIN_USERNAME"] = "admin"
os.environ["SQLAGENT_ADMIN_PASSWORD"] = "test-password"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "test-password"


@pytest.fixture(autouse=True)
def offline_dns(monkeypatch):
    """测试不依赖真实 DNS：域名一律解析成公网地址。

    需要「解析到内网」的用例，自己在测试里 monkeypatch 掉 app.netguard._resolve。
    """
    monkeypatch.setattr("app.netguard._resolve", lambda host, port: ["93.184.216.34"])


@pytest.fixture(autouse=True)
def clean_rate_limits():
    """每个用例都从零开始计失败次数，避免互相干扰。"""
    from app.api.auth import reset_login_limits

    reset_login_limits()
    yield
    reset_login_limits()


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def demo_sqlite() -> Path:
    """一个带中文业务语义的小库，用来验证 introspect 全链路。"""
    path = _fresh_dir(_TMP, "shop-") / "shop.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT,
            is_test INTEGER DEFAULT 0
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            amount REAL NOT NULL,
            status TEXT DEFAULT 'paid',
            created_at TEXT
        );
        INSERT INTO customers (name, city, is_test) VALUES ('张三', '上海', 0), ('李四', '北京', 1);
        INSERT INTO orders (customer_id, amount, status, created_at)
            VALUES (1, 99.5, 'paid', '2026-01-05'), (2, 20.0, 'cancelled', '2026-02-11');
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def sqlite_datasource(client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path):
    response = client.post(
        "/api/v1/datasources",
        headers=admin_headers,
        json={
            "name": "演示库",
            "type": "sqlite",
            "database": str(demo_sqlite),
            "safety_level": "L0",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    yield payload
    client.delete(f"/api/v1/datasources/{payload['id']}", headers=admin_headers)