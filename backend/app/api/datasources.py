"""数据源管理：增删查、连通性测试、结构快照。

注意：凭证只进不出。接口永远不会返回口令，只返回 ``has_write_credential``。
归属校验统一走 ``store.owned_datasource``，不要在路由里重复实现。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import uploads
from app.audit import Auditor
from app.config import settings
from app.deps import Principal, get_auditor, get_principal, get_session
from app.dialects import get_dialect, test_connection
from app.engine.context import invalidate_cache
from app.introspect import introspect
from app.models import Datasource, utcnow
from app.schemas import DatasourceCreate, DatasourceOut, SchemaOut, TestResult
from app.security import get_secret_box
from app.store import owned_datasource, read_password

router = APIRouter(prefix="/datasources", tags=["datasources"])

SAFETY_LEVELS = {"L0", "L1", "L2", "L3"}


def _to_out(ds: Datasource) -> DatasourceOut:
    return DatasourceOut(
        id=ds.id,
        name=ds.name,
        type=ds.type,
        host=ds.host,
        port=ds.port,
        database=ds.database,
        username=ds.username,
        safety_level=ds.safety_level,
        is_prod=ds.is_prod,
        has_write_credential=bool(ds.writable_username and ds.writable_password_enc),
        last_check_ok=ds.last_check_ok,
        last_checked_at=ds.last_checked_at,
        created_at=ds.created_at,
    )


@router.get("", response_model=list[DatasourceOut])
async def list_datasources(
    user: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[DatasourceOut]:
    rows = await session.scalars(
        select(Datasource)
        .where(Datasource.workspace_id == user.workspace_id)
        .order_by(Datasource.id.desc())
    )
    return [_to_out(ds) for ds in rows]


@router.post("", response_model=DatasourceOut, status_code=status.HTTP_201_CREATED)
async def create_datasource(
    body: DatasourceCreate,
    user: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    auditor: Auditor = Depends(get_auditor),
) -> DatasourceOut:
    box = get_secret_box()
    dialect = get_dialect(body.type)
    ds = Datasource(
        workspace_id=user.workspace_id,
        name=body.name,
        type=body.type,
        host=body.host,
        port=body.port or dialect.default_port,
        database=body.database,
        username=body.username,
        password_enc=box.encrypt(body.password) if body.password else "",
        writable_username=body.writable_username or None,
        writable_password_enc=box.encrypt(body.writable_password) if body.writable_password else None,
        safety_level=body.safety_level,
        is_prod=body.is_prod,
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)

    await auditor.log(
        "datasource.create",
        target_type="datasource",
        target_id=ds.id,
        detail={
            "name": ds.name,
            "type": ds.type,
            "safety_level": ds.safety_level,
            "is_prod": ds.is_prod,
            "has_write_credential": bool(ds.writable_password_enc),
        },
    )
    return _to_out(ds)


@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_datasource(
    datasource_id: int,
    user: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    auditor: Auditor = Depends(get_auditor),
) -> None:
    ds = await owned_datasource(session, user.workspace_id, datasource_id)
    name, ds_type, database = ds.name, ds.type, ds.database
    await session.delete(ds)
    await session.commit()
    # SQLite 的 rowid 可能被复用：不清缓存的话，新建的数据源可能读到旧表结构
    invalidate_cache(datasource_id)
    # 上传来的文件跟着删；手填的服务器路径不碰
    removed_file = uploads.remove_upload(database)

    await auditor.log(
        "datasource.delete",
        target_type="datasource",
        target_id=datasource_id,
        detail={"name": name, "type": ds_type, "removed_upload": removed_file},
    )


@router.post("/upload", response_model=DatasourceOut, status_code=status.HTTP_201_CREATED)
async def upload_datasource(
    file: UploadFile = File(..., description="SQLite 数据库文件（.db / .sqlite / .sqlite3）"),
    name: str = Form(""),
    safety_level: str = Form("L0"),
    user: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    auditor: Auditor = Depends(get_auditor),
) -> DatasourceOut:
    """上传一个 SQLite 文件并直接建成数据源。

    先落盘、再试读结构：**读不出来就删文件**，不让"列表里有个打不开的数据源"这种事发生。
    """
    if not settings.allow_upload:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "当前部署未开放文件上传")
    if safety_level not in SAFETY_LEVELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "安全等级不合法")

    try:
        path = await uploads.save_sqlite(file, user.workspace_id)
    except uploads.UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    ds = Datasource(
        workspace_id=user.workspace_id,
        name=(name.strip() or Path(file.filename or "").stem or "上传的数据库")[:128],
        type="sqlite",
        database=str(path),
        safety_level=safety_level,
        is_prod=False,
    )

    # 先 flush 拿到 id：introspect 要把它填进 SchemaOut，没 id 会校验失败
    session.add(ds)
    await session.flush()
    try:
        schema = await introspect(ds, "")
        if not schema.tables:
            raise ValueError("库里没有任何表")
    except Exception as exc:  # noqa: BLE001 - 文件坏了就明确告诉用户
        await session.rollback()
        uploads.remove_upload(str(path))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"这个文件读不出来：{exc}") from exc

    await session.commit()
    await session.refresh(ds)

    await auditor.log(
        "datasource.upload",
        target_type="datasource",
        target_id=ds.id,
        detail={
            "name": ds.name,
            "filename": (file.filename or "")[:120],
            "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
            "tables": len(schema.tables),
        },
    )
    return _to_out(ds)


@router.post("/{datasource_id}/test", response_model=TestResult)
async def test_datasource(
    datasource_id: int,
    user: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    auditor: Auditor = Depends(get_auditor),
) -> TestResult:
    ds = await owned_datasource(session, user.workspace_id, datasource_id)
    result = await test_connection(ds, read_password(ds))

    ds.last_check_ok = result.ok
    ds.last_checked_at = utcnow()
    await session.commit()

    await auditor.log(
        "datasource.test",
        target_type="datasource",
        target_id=ds.id,
        result="ok" if result.ok else "error",
        detail={"message": result.message, "latency_ms": result.latency_ms},
    )
    return result


@router.get("/{datasource_id}/schema", response_model=SchemaOut)
async def get_schema(
    datasource_id: int,
    user: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    auditor: Auditor = Depends(get_auditor),
) -> SchemaOut:
    ds = await owned_datasource(session, user.workspace_id, datasource_id)
    try:
        schema = await introspect(ds, read_password(ds))
    except Exception as exc:  # noqa: BLE001 - 驱动异常统一转成 400
        await auditor.log(
            "datasource.schema",
            target_type="datasource",
            target_id=ds.id,
            result="error",
            detail={"error": str(exc)[:300]},
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"读取表结构失败：{exc}") from exc

    await auditor.log(
        "datasource.schema",
        target_type="datasource",
        target_id=ds.id,
        detail={"tables": len(schema.tables)},
    )
    return schema