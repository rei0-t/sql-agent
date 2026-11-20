"""凭证安全：口令不能以明文落库或回显。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.security import SecretBox, hash_password, verify_password

PLAINTEXT = "SuperSecret#2026"


def test_password_hash_roundtrip() -> None:
    stored = hash_password("correct horse battery staple")
    assert stored.startswith("scrypt$")
    assert verify_password("correct horse battery staple", stored) is True
    assert verify_password("wrong", stored) is False
    assert verify_password("anything", "garbage") is False


def test_secret_box_roundtrip() -> None:
    box = SecretBox("unit-test-key")
    token = box.encrypt(PLAINTEXT)
    assert PLAINTEXT not in token
    assert box.decrypt(token) == PLAINTEXT


def test_datasource_password_is_encrypted_at_rest(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path
) -> None:
    created = client.post(
        "/api/v1/datasources",
        headers=admin_headers,
        json={
            "name": "加密检查",
            "type": "sqlite",
            "database": str(demo_sqlite),
            "username": "reader",
            "password": PLAINTEXT,
        },
    )
    assert created.status_code == 201
    ds_id = created.json()["id"]

    meta_path = settings.resolved_database_url.replace("sqlite+aiosqlite:///", "")
    conn = sqlite3.connect(meta_path)
    try:
        row = conn.execute(
            "SELECT password_enc FROM datasources WHERE id = ?", (ds_id,)
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    stored = row[0]
    assert PLAINTEXT not in stored
    assert stored  # 密文非空

    # 接口不回显任何凭证字段
    detail = client.get("/api/v1/datasources", headers=admin_headers).json()
    for item in detail:
        assert "password" not in item
        assert "password_enc" not in item

    client.delete(f"/api/v1/datasources/{ds_id}", headers=admin_headers)


def test_audit_log_records_sensitive_actions(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path
) -> None:
    client.post(
        "/api/v1/datasources",
        headers=admin_headers,
        json={"name": "审计检查", "type": "sqlite", "database": str(demo_sqlite)},
    )

    meta_path = settings.resolved_database_url.replace("sqlite+aiosqlite:///", "")
    conn = sqlite3.connect(meta_path)
    try:
        actions = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT action FROM audit_logs "
                "WHERE action IN ('datasource.create', 'auth.login')"
            )
        }
    finally:
        conn.close()

    assert "datasource.create" in actions
    assert "auth.login" in actions