"""元数据库：引擎、会话、初始化与首个管理员账号。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base, User, Workspace
from app.security import hash_password

engine = create_async_engine(settings.resolved_database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """建表并确保至少存在一个管理员。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_bootstrap_admin()


async def ensure_bootstrap_admin() -> None:
    async with SessionLocal() as session:
        existing = await session.scalar(select(func.count()).select_from(User))
        if existing:
            return
        workspace = Workspace(name="默认工作空间")
        session.add(workspace)
        await session.flush()
        session.add(
            User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                role="admin",
                workspace_id=workspace.id,
            )
        )
        await session.commit()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session