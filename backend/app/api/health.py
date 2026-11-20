"""健康检查：给部署编排和监控用，不需要鉴权。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    database = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - 健康检查只需要一个布尔结果
        database = "error"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "version": settings.version,
        "database": database,
    }