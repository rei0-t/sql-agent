"""重置某个工作空间的提问额度（或全部）。

额度落在 ``workspaces.questions_used``，管理员在接口里不受限制，
这个脚本是给"想让某个访客重新试用"或"批量清空"用的。

用法：
    python scripts/reset_quota.py --list
    python scripts/reset_quota.py --workspace 3
    python scripts/reset_quota.py --all
"""

from __future__ import annotations

import argparse
import asyncio

from _bootstrap import ensure_backend

BACKEND = ensure_backend()

from app.config import settings
from app.models import User, Workspace
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main(args: argparse.Namespace) -> int:
    engine = create_async_engine(settings.resolved_database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            if args.list:
                rows = (
                    await session.execute(
                        select(Workspace.id, Workspace.name, Workspace.questions_used)
                        .order_by(Workspace.id)
                    )
                ).all()
                print(f"额度上限 {settings.chat_max_questions}（0 = 不限）")
                for ws_id, name, used in rows:
                    owner = await session.scalar(
                        select(User.username).where(User.workspace_id == ws_id)
                    )
                    print(f"  #{ws_id:<3} 已用 {used:<4} {owner or '—':<20} {name}")
                return 0

            if args.all:
                await session.execute(update(Workspace).values(questions_used=0))
                await session.commit()
                print("已重置所有工作空间")
                return 0

            workspace = await session.get(Workspace, args.workspace)
            if workspace is None:
                print(f"工作空间 #{args.workspace} 不存在")
                return 1
            workspace.questions_used = 0
            await session.commit()
            print(f"已重置工作空间 #{workspace.id}（{workspace.name}）")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="查看或重置提问额度")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="列出所有工作空间的用量")
    group.add_argument("--workspace", type=int, help="重置指定工作空间")
    group.add_argument("--all", action="store_true", help="重置全部")
    raise SystemExit(asyncio.run(main(parser.parse_args())))