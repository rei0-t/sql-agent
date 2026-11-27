"""清理没有被任何数据源引用的上传文件。

什么时候会有孤儿文件：
- 上传失败留下的临时碎片（正常路径已经会清）
- 直接改数据库删了数据源（绕过接口）
- 早期版本没有连带删除

用法：
    python scripts/cleanup_uploads.py              # 只列出，不删
    python scripts/cleanup_uploads.py --apply      # 真删
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from _bootstrap import ensure_backend

BACKEND = ensure_backend()

from app.config import settings
from app.models import Datasource
from app.uploads import upload_root
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main(apply: bool) -> int:
    root = upload_root()
    if not root.is_dir():
        print("没有上传目录，什么都不用做")
        return 0

    engine = create_async_engine(settings.resolved_database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            referenced = {
                (item or "").strip()
                for item in await session.scalars(select(Datasource.database))
                if item
            }
    finally:
        await engine.dispose()

    files = [item for item in root.rglob("*") if item.is_file()]
    orphans = [item for item in files if str(item) not in referenced]

    print(f"上传目录: {root}")
    print(f"文件总数: {len(files)}，被引用: {len(files) - len(orphans)}，孤儿: {len(orphans)}")

    total = 0
    for item in orphans:
        size = item.stat().st_size
        total += size
        print(f"  {'删除' if apply else '可删'}  {item.relative_to(root)}  ({size // 1024} KB)")
        if apply:
            item.unlink(missing_ok=True)

    if orphans:
        print(f"合计 {total / (1024 * 1024):.2f} MB")
    if not apply and orphans:
        print("\n加 --apply 才会真的删除")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理未被引用的上传文件")
    parser.add_argument("--apply", action="store_true", help="真的删除（默认只列出）")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.apply)))