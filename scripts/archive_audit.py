"""审计归档：把保留期之外的记录导出成 JSONL.gz，再从库里删掉。

为什么要单独一个脚本而不是后台任务：
- 归档是**破坏性**操作，应该由运维显式触发、可 dry-run、可留档
- 放进 Web 请求里会拖长尾延迟

用法：
    python scripts/archive_audit.py --dry-run          # 只统计，不动数据
    python scripts/archive_audit.py --days 180         # 导出并删除 180 天前的
    python scripts/archive_audit.py --days 180 --out /var/backups/sql-agent

建议放 crontab（每月一次）：
    0 4 1 * * cd /opt/sql-agent && python scripts/archive_audit.py --days 180 >> /var/log/sql-agent-archive.log 2>&1
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if (BACKEND / "app").is_dir():
    sys.path.insert(0, str(BACKEND))

from app.config import settings
from app.models import AuditLog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _row_to_dict(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "actor_id": row.actor_id,
        "actor_name": row.actor_name,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "result": row.result,
        "detail": json.loads(row.detail) if row.detail else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def archive(days: int, out_dir: Path, dry_run: bool) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    engine = create_async_engine(settings.resolved_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            rows = (
                await session.scalars(
                    select(AuditLog)
                    .where(AuditLog.created_at < cutoff)
                    .order_by(AuditLog.id)
                )
            ).all()

            print(f"保留期 {days} 天，截止 {cutoff.isoformat(timespec='seconds')}")
            print(f"待归档 {len(rows)} 条")
            if not rows:
                return

            oldest = rows[0].created_at
            newest = rows[-1].created_at
            print(f"时间范围：{oldest.isoformat(timespec='seconds')} ~ {newest.isoformat(timespec='seconds')}")

            if dry_run:
                print("--dry-run：不写文件、不删数据")
                return

            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            path = out_dir / f"audit-archive-{stamp}.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(_row_to_dict(row), ensure_ascii=False, default=str) + "\n")
            print(f"已导出到 {path} （{path.stat().st_size // 1024} KB）")

            ids = [row.id for row in rows]
            await session.execute(delete(AuditLog).where(AuditLog.id.in_(ids)))
            await session.commit()
            print(f"已从库里删除 {len(ids)} 条")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="归档并清理旧审计")
    parser.add_argument("--days", type=int, default=settings.audit_retention_days)
    parser.add_argument("--out", default="backups")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.days < 1:
        raise SystemExit("--days 必须 >= 1")

    asyncio.run(archive(args.days, Path(args.out), args.dry_run))


if __name__ == "__main__":
    main()