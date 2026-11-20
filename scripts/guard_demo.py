"""教学脚本：把各种「坏 SQL」喂给只读闸门，看它怎么拦。

不连数据库、不调用大模型，纯粹演示 guard.py 的判断逻辑。

用法：
    python scripts/guard_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if (BACKEND / "app").is_dir():
    sys.path.insert(0, str(BACKEND))

from app.engine.guard import GuardError, check

ALLOWED = {"orders", "customers"}
CASES = [
    ("最普通的查询", "SELECT 1"),
    ("没写 LIMIT", "SELECT * FROM orders"),
    ("写操作", "DELETE FROM orders"),
    ("读了没授权的表", "SELECT * FROM secret_table"),
    ("多语句注入", "SELECT 1; DROP TABLE orders"),
    ("读文件函数", "SELECT LOAD_FILE('/etc/passwd')"),
    ("LIMIT 给得太大", "SELECT * FROM orders LIMIT 999999"),
    ("CTE（临时表名不该被当成越权）", "WITH t AS (SELECT 1 AS x) SELECT * FROM t"),
    ("子查询里的越权", "SELECT * FROM orders WHERE id IN (SELECT id FROM secret_table)"),
]


def main() -> None:
    print(f"允许访问的表：{', '.join(sorted(ALLOWED))}\n")
    passed = blocked = 0
    for title, sql in CASES:
        try:
            guarded = check(sql, dialect="sqlite", allow_tables=ALLOWED, max_rows=200)
            passed += 1
            print(f"✅ {title}")
            print(f"   输入: {sql}")
            print(f"   放行: {guarded.sql}")
        except GuardError as exc:
            blocked += 1
            print(f"⛔ {title}")
            print(f"   输入: {sql}")
            print(f"   原因: [{exc.code}] {exc.message}")
        print()

    print(f"小结：放行 {passed} 条，拦下 {blocked} 条")
    print("注意前两条：闸门不是「挑刺」，而是把 SQL 规范成能安全执行的样子（自动补 LIMIT）。")


if __name__ == "__main__":
    main()