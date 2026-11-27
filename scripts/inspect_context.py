"""教学脚本：打印「模型实际收到的上下文」，不调用大模型、不花钱、不写库。

这是理解本项目最快的一步：你会看到 BM25 选了哪几张表、列注释长什么样、
采样数据是什么、业务口径是怎么拼进去的。

用法（在仓库根目录跑）：

    python scripts/inspect_context.py --sqlite data/demo/shop.db --question "2026 年第三季度华东区的 GMV 是多少"
    python scripts/inspect_context.py --datasource-id 1 --question "退款率是多少"

参数：
    --sqlite PATH       直接指向一个 SQLite 文件（不需要元数据库）
    --datasource-id N   从元数据库里读一个已配置的数据源（MySQL/PG 也能用）
    --question TEXT     用户问题
    --limit N           只看前 N 张表（默认用配置里的 schema_max_tables）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if (BACKEND / "app").is_dir():
    sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.engine.context import build_context  # noqa: E402
from app.engine.semantics import load_semantics  # noqa: E402
from app.models import Datasource  # noqa: E402


def _from_meta(datasource_id: int) -> Datasource:
    """从元数据库读一个数据源（跳过 ORM，直接 sqlite 读，脚本更轻）。"""
    import sqlite3

    meta = settings.resolved_database_url.replace("sqlite+aiosqlite:///", "")
    conn = sqlite3.connect(meta)
    try:
        row = conn.execute(
            "SELECT id, workspace_id, name, type, host, port, database, username, safety_level, is_prod "
            "FROM datasources WHERE id = ?",
            (datasource_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise SystemExit(f"元数据库里没有 id={datasource_id} 的数据源")

    return Datasource(
        id=row[0],
        workspace_id=row[1],
        name=row[2],
        type=row[3],
        host=row[4],
        port=row[5],
        database=row[6],
        username=row[7],
        safety_level=row[8],
        is_prod=row[9],
    )


def _local_sqlite(path: str, name: str = "本地 SQLite") -> Datasource:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    if not resolved.exists():
        raise SystemExit(f"找不到文件：{resolved}")
    return Datasource(
        id=0,
        workspace_id=0,
        name=name,
        type="sqlite",
        database=str(resolved),
        safety_level="L0",
        is_prod=False,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="打印模型收到的上下文")
    parser.add_argument("--question", required=True)
    parser.add_argument("--sqlite")
    parser.add_argument("--datasource-id", type=int)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.sqlite:
        ds = _local_sqlite(args.sqlite)
    elif args.datasource_id is not None:
        ds = _from_meta(args.datasource_id)
    else:
        raise SystemExit("要么给 --sqlite，要么给 --datasource-id")

    if args.limit:
        settings.schema_max_tables = args.limit

    semantics = load_semantics()
    context = await build_context(ds, "", args.question, semantics_text=semantics.render())

    print("=" * 72)
    print(f"问题：{args.question}")
    print(f"数据源：{ds.name}（{ds.type}）")
    print(f"库里的表：{len(context.candidate_tables)} 张")
    print(f"BM25 选中：{len(context.tables)} 张 → {', '.join(context.tables)}")
    loaded = "未配置（semantics.yaml 不存在或为空）"
    if not semantics.empty:
        loaded = f"已加载 {len(semantics.metrics)} 个指标 / {len(semantics.examples)} 条示例"
    print(f"语义层：{loaded}")
    print("=" * 72)
    print()
    print(context.text)
    print()
    print("=" * 72)
    chars = len(context.text)
    print(f"上下文长度：{chars} 字符 ≈ {chars // 3} ~ {chars // 2} token（中英混排的粗估）")
    print("提示：这段文本会原样拼进 plan 和 generate 两次调用的 user 消息里。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)