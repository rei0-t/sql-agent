"""迁移命令行。

    python scripts/migrate.py                  # 升级到最新（新库会自动 stamp 到 baseline）
    python scripts/migrate.py --revision "msg" # 按当前模型自动生成新 revision（开发用）
    python scripts/migrate.py --current        # 看当前版本
    python scripts/migrate.py --history        # 看历史

为什么需要 --stamp 逻辑：v0.1 的库是用 create_all 建的，没有 alembic_version 表。
直接 upgrade 会因为「表已存在」失败，所以先判断：有表没版本 → stamp baseline。
"""

from __future__ import annotations

import argparse
import asyncio

from _bootstrap import ensure_backend

BACKEND = ensure_backend()

from alembic import command
from alembic.config import Config
from app.config import settings
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

BASELINE = "0001_initial"


def _config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


async def _state() -> tuple[bool, bool]:
    """返回 (有没有业务表, 有没有 alembic_version)。"""
    engine = create_async_engine(settings.resolved_database_url)
    try:
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    finally:
        await engine.dispose()
    has_version = "alembic_version" in names
    has_tables = bool(names - {"alembic_version"})
    return has_tables, has_version


def main() -> None:
    parser = argparse.ArgumentParser(description="数据库迁移")
    parser.add_argument("--revision", metavar="MESSAGE", help="自动生成一个新的 revision")
    parser.add_argument("--current", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--sql", action="store_true", help="只打印 SQL，不执行")
    args = parser.parse_args()

    cfg = _config()
    print(f"数据库: {settings.resolved_database_url}")

    if args.revision:
        command.revision(cfg, message=args.revision, autogenerate=True)
        return
    if args.current:
        command.current(cfg)
        return
    if args.history:
        command.history(cfg)
        return
    if args.sql:
        command.upgrade(cfg, "head", sql=True)
        return

    has_tables, has_version = asyncio.run(_state())
    if has_tables and not has_version:
        print(f"检测到 v0.1 的老库（有表、无迁移版本），先把基线标成 {BASELINE}")
        command.stamp(cfg, BASELINE)

    command.upgrade(cfg, "head")
    print("已升级到最新版本")


if __name__ == "__main__":
    main()