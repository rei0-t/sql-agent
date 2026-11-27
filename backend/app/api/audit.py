"""审计查询接口：列表、筛选项、汇总。

审计表只追加，所以这里**只有 GET**，没有任何修改或删除入口。
所有查询都限定在当前工作空间内。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import Principal, get_principal, get_session
from app.models import AuditLog
from app.schemas import AuditBucketOut, AuditEntryOut, AuditPageOut

router = APIRouter(prefix="/audit", tags=["audit"])


def _parse_detail(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"raw": raw}


def _to_out(row: AuditLog) -> AuditEntryOut:
    return AuditEntryOut(
        id=row.id,
        created_at=row.created_at,
        actor_name=row.actor_name,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        result=row.result,
        detail=_parse_detail(row.detail),
    )


@router.get("", response_model=AuditPageOut)
async def list_audit(
    action: str | None = Query(default=None, max_length=64),
    result: str | None = Query(default=None, max_length=16),
    actor: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=200, description="在 detail 里搜文本"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> AuditPageOut:
    # 工作空间隔离。管理员额外能看到 workspace 0 的全局安全事件
    # （未知用户名的登录失败、被限流的尝试——这些在写审计时还不知道属于谁）。
    if user.is_admin:
        conditions = [AuditLog.workspace_id.in_([user.workspace_id, 0])]
    else:
        conditions = [AuditLog.workspace_id == user.workspace_id]
    if action:
        conditions.append(AuditLog.action == action)
    if result:
        conditions.append(AuditLog.result == result)
    if actor:
        conditions.append(AuditLog.actor_name.like(f"%{actor}%"))
    if q:
        conditions.append(AuditLog.detail.like(f"%{q}%"))

    total = await session.scalar(
        select(func.count()).select_from(AuditLog).where(*conditions)
    )
    rows = await session.scalars(
        select(AuditLog).where(*conditions).order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    )
    return AuditPageOut(
        items=[_to_out(row) for row in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.get("/actions", response_model=list[str])
async def list_actions(
    user: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    """这个工作空间出现过的动作类型，用来填筛选下拉框。"""
    rows = await session.scalars(
        select(AuditLog.action)
        .where(AuditLog.workspace_id == user.workspace_id)
        .distinct()
        .order_by(AuditLog.action)
    )
    return list(rows)


@router.get("/summary", response_model=list[AuditBucketOut])
async def audit_summary(
    days: int = Query(default=7, ge=1, le=90),
    user: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[AuditBucketOut]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await session.execute(
        select(AuditLog.action, AuditLog.result, func.count())
        .where(AuditLog.workspace_id == user.workspace_id, AuditLog.created_at >= since)
        .group_by(AuditLog.action, AuditLog.result)
        .order_by(func.count().desc())
    )
    return [AuditBucketOut(action=action, result=result, count=int(count)) for action, result, count in rows.all()]