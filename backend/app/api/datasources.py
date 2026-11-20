"""数据源管理：增删查、连通性测试、结构快照。

注意：凭证只进不出。接口永远不会返回口令，只返回 ``has_write_credential``。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.deps import Principal, get_principal, get_session
from app.dialects import get_dialect, test_connection
from app.introspect import introspect
from app.models import Datasource, utcnow
from app.schemas import DatasourceCreate, DatasourceOut, SchemaOut, TestResult
from app.security import get_secret_box

router = APIRouter(prefix="/datasources", tags=["datasources"])


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


async def _get_owned(session: AsyncSession, user: Principal, datasource_id: int) -> Datasource:
    ds = await session.get(Datasource, datasource_id)
    if ds is None or ds.workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "数据源不存在")
    return ds


def _read_password(ds: Datasource) -> str:
    if not ds.password_enc:
        return ""
    return get_secret_box().decrypt(ds.password_enc)


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

    await audit.record(
        session,
        workspace_id=user.workspace_id,
        action="datasource.create",
        actor_id=user.id,
        actor_name=user.username,
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
) -> None:
    ds = await _get_owned(session, user, datasource_id)
    name, ds_type = ds.name, ds.type
    await session.delete(ds)
    await session.commit()
    await audit.record(
        session,
        workspace_id=user.workspace_id,
        action="datasource.delete",
        actor_id=user.id,
        actor_name=user.username,
        target_type="datasource",
        target_id=datasource_id,
        detail={"name": name, "type": ds_type},
    )


@router.post("/{datasource_id}/test", response_model=TestResult)
async def test_datasource(
    datasource_id: int,
    user: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> TestResult:
    ds = await _get_owned(session, user, datasource_id)
    result = await test_connection(ds, _read_password(ds))

    ds.last_check_ok = result.ok
    ds.last_checked_at = utcnow()
    await session.commit()

    await audit.record(
        session,
        workspace_id=user.workspace_id,
        action="datasource.test",
        actor_id=user.id,
        actor_name=user.username,
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
) -> SchemaOut:
    ds = await _get_owned(session, user, datasource_id)
    try:
        schema = await introspect(ds, _read_password(ds))
    except Exception as exc:  # noqa: BLE001 - 驱动异常统一转成 400
        await audit.record(
            session,
            workspace_id=user.workspace_id,
            action="datasource.schema",
            actor_id=user.id,
            actor_name=user.username,
            target_type="datasource",
            target_id=ds.id,
            result="error",
            detail={"error": str(exc)[:300]},
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"读取表结构失败：{exc}") from exc

    await audit.record(
        session,
        workspace_id=user.workspace_id,
        action="datasource.schema",
        actor_id=user.id,
        actor_name=user.username,
        target_type="datasource",
        target_id=ds.id,
        detail={"tables": len(schema.tables)},
    )
    return schema