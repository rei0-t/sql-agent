"""审计：所有敏感动作写一条只追加记录。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record(
    session: AsyncSession,
    *,
    workspace_id: int,
    action: str,
    actor_id: int | None = None,
    actor_name: str = "",
    target_type: str | None = None,
    target_id: str | int | None = None,
    result: str = "ok",
    detail: dict[str, Any] | None = None,
) -> None:
    """独立提交，保证失败的请求也留下痕迹。"""
    session.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_id=actor_id,
            actor_name=actor_name,
            action=action,
            target_type=target_type,
            target_id=None if target_id is None else str(target_id),
            result=result,
            detail=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
        )
    )
    await session.commit()