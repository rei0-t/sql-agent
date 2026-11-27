"""Alembic 运行环境。

连接串不写在 alembic.ini 里，统一从 ``app.config.settings`` 读——
这样命令行迁移和应用启动用的是同一份配置（环境变量优先）。

本项目用异步驱动（aiosqlite / asyncpg），所以在线迁移走 async engine + run_sync。
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.resolved_database_url)

target_metadata = Base.metadata


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        # SQLite 的 ALTER TABLE 能力有限，batch 模式会把变更重建成「建新表 + 拷数据」
        render_as_batch=True,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=settings.resolved_database_url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()