"""SQLite 文件上传：落盘、配额、删数据源时清理。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings


@pytest.fixture()
def isolated_uploads(tmp_path, monkeypatch):
    """把 data_dir 换成本用例专属目录，配额从 0 开始算。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


def _upload(
    client: TestClient,
    headers: dict[str, str],
    path: Path,
    *,
    name: str = "",
    safety_level: str = "L0",
    filename: str | None = None,
    content: bytes | None = None,
):
    payload = content if content is not None else path.read_bytes()
    return client.post(
        "/api/v1/datasources/upload",
        headers=headers,
        files={"file": (filename or path.name, payload, "application/octet-stream")},
        data={"name": name, "safety_level": safety_level},
    )


def test_upload_creates_queryable_datasource(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path, isolated_uploads
) -> None:
    response = _upload(client, admin_headers, demo_sqlite, name="上传的库")
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["type"] == "sqlite"
    assert body["name"] == "上传的库"
    stored = Path(body["database"])
    assert stored.parent.parent.name == "uploads", "上传的文件必须落在受管目录里"
    assert stored.is_file()

    schema = client.get(f"/api/v1/datasources/{body['id']}/schema", headers=admin_headers)
    assert schema.status_code == 200
    tables = {t["name"] for t in schema.json()["tables"]}
    assert {"customers", "orders"} <= tables

    client.delete(f"/api/v1/datasources/{body['id']}", headers=admin_headers)


def test_upload_defaults_name_from_filename(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path, isolated_uploads
) -> None:
    response = _upload(client, admin_headers, demo_sqlite, filename="季度报表.db")
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "季度报表"
    client.delete(f"/api/v1/datasources/{response.json()['id']}", headers=admin_headers)


def test_upload_rejects_non_sqlite(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path, isolated_uploads
) -> None:
    response = _upload(client, admin_headers, demo_sqlite, content=b"just some text", filename="x.db")
    assert response.status_code == 400
    assert "SQLite" in response.json()["detail"]


def test_upload_rejects_wrong_extension(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path, isolated_uploads
) -> None:
    response = _upload(client, admin_headers, demo_sqlite, filename="notes.txt")
    assert response.status_code == 400
    assert ".db" in response.json()["detail"]


def test_upload_rejects_empty_file(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path, isolated_uploads
) -> None:
    response = _upload(client, admin_headers, demo_sqlite, content=b"", filename="empty.db")
    assert response.status_code == 400


def test_per_file_quota(
    client: TestClient,
    admin_headers: dict[str, str],
    demo_sqlite: Path,
    isolated_uploads,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "upload_max_mb_per_file", 0)
    response = _upload(client, admin_headers, demo_sqlite)
    assert response.status_code == 400
    assert "上限" in response.json()["detail"]


def test_workspace_quota(
    client: TestClient,
    admin_headers: dict[str, str],
    demo_sqlite: Path,
    isolated_uploads,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "upload_max_mb_per_workspace", 0)
    response = _upload(client, admin_headers, demo_sqlite)
    assert response.status_code == 400
    assert "上限" in response.json()["detail"]


def test_total_quota(
    client: TestClient,
    admin_headers: dict[str, str],
    demo_sqlite: Path,
    isolated_uploads,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "upload_max_mb_total", 0)
    response = _upload(client, admin_headers, demo_sqlite)
    assert response.status_code == 400
    assert "空间已满" in response.json()["detail"]


def test_upload_can_be_disabled(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path, isolated_uploads, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "allow_upload", False)
    response = _upload(client, admin_headers, demo_sqlite)
    assert response.status_code == 403


def test_upload_requires_auth(client: TestClient, demo_sqlite: Path, isolated_uploads) -> None:
    client.cookies.clear()
    response = _upload(client, {}, demo_sqlite)
    assert response.status_code == 401


def test_delete_removes_uploaded_file(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path, isolated_uploads
) -> None:
    created = _upload(client, admin_headers, demo_sqlite).json()
    stored = Path(created["database"])
    assert stored.exists()

    assert client.delete(f"/api/v1/datasources/{created['id']}", headers=admin_headers).status_code == 204
    assert not stored.exists(), "删数据源要连带删掉上传的文件"


def test_delete_keeps_external_sqlite_file(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path, isolated_uploads
) -> None:
    """手填的服务器路径不归我们管，删数据源不能把别人的库删掉。"""
    response = client.post(
        "/api/v1/datasources",
        headers=admin_headers,
        json={"name": "外部库", "type": "sqlite", "database": str(demo_sqlite), "safety_level": "L0"},
    )
    assert response.status_code == 201

    client.delete(f"/api/v1/datasources/{response.json()['id']}", headers=admin_headers)
    assert demo_sqlite.exists()


def test_broken_sqlite_is_not_kept(
    client: TestClient, admin_headers: dict[str, str], isolated_uploads, tmp_path
) -> None:
    """文件头像 SQLite 但内容坏：要报错，且不能留一个打不开的数据源。"""
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"SQLite format 3\x00" + b"\x00" * 4096)
    before = list((tmp_path / "uploads").rglob("*.db")) if (tmp_path / "uploads").exists() else []

    response = _upload(client, admin_headers, broken)
    assert response.status_code == 400

    listing = client.get("/api/v1/datasources", headers=admin_headers).json()
    assert all(item["name"] != "broken" for item in listing)
    after = list((tmp_path / "uploads").rglob("*.db")) if (tmp_path / "uploads").exists() else []
    assert len(after) == len(before), "读不出来的文件必须被删掉"


def test_upload_is_audited(
    client: TestClient, admin_headers: dict[str, str], demo_sqlite: Path, isolated_uploads
) -> None:
    created = _upload(client, admin_headers, demo_sqlite).json()
    page = client.get(
        "/api/v1/audit", headers=admin_headers, params={"action": "datasource.upload"}
    ).json()
    assert page["total"] >= 1
    client.delete(f"/api/v1/datasources/{created['id']}", headers=admin_headers)
