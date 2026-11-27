"""生成演示用的中文电商 SQLite 库（CLI）。

生成逻辑在 ``app/demo.py``：应用启动时也要用它造示例库，所以不能只留在脚本里。

用法::

    python scripts/seed_demo.py                    # 默认写到 data/demo/shop.db
    python scripts/seed_demo.py --orders 50000     # 造更大的库压测
"""

from __future__ import annotations

import argparse
from pathlib import Path

from _bootstrap import ensure_backend

BACKEND = ensure_backend()

from app.demo import DEFAULT_ORDERS, DEFAULT_SEED, build_demo_database


def main() -> None:
    parser = argparse.ArgumentParser(description="生成演示用中文电商 SQLite 库")
    parser.add_argument("--out", default="data/demo/shop.db", help="输出路径")
    parser.add_argument("--orders", type=int, default=DEFAULT_ORDERS, help="订单数量")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子（可复现）")
    args = parser.parse_args()

    out = Path(args.out)
    build_demo_database(out, orders=args.orders, seed=args.seed)
    print(f"已生成 {out}  ({out.stat().st_size / 1024:.0f} KB, {args.orders} 笔订单)")


if __name__ == "__main__":
    main()