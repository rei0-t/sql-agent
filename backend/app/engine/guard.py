"""只读通道的安全闸门。

职责：把模型生成的 SQL 变成「可以安全执行的一条 SELECT」。
边界要记住：闸门负责让错误尽早暴露，**真正的安全边界是只读账号与只读连接**。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

# 逐版本兼容地收集禁用节点类型
_FORBIDDEN_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Drop",
    "Alter",
    "Create",
    "Merge",
    "Command",
    "TruncateTable",
    "Into",
    "Attach",
    "Detach",
    "Grant",
    "Transaction",
    "Commit",
    "Rollback",
    "Use",
    "Set",
    "Copy",
    "LoadData",
)
FORBIDDEN: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name) for name in _FORBIDDEN_NAMES if hasattr(exp, name)
)

BLOCKED_FUNCTIONS = {
    "LOAD_FILE",
    "LOAD_EXTENSION",
    "READ_CSV",
    "READ_PARQUET",
    "PG_READ_FILE",
    "PG_READ_BINARY_FILE",
    "PG_LS_DIR",
    "XP_CMDSHELL",
    "SLEEP",
    "BENCHMARK",
    "DBLINK",
    "LO_IMPORT",
}

DIALECT_BY_TYPE = {"sqlite": "sqlite", "mysql": "mysql", "postgres": "postgres"}


class GuardError(ValueError):
    """SQL 未通过闸门。code 用于后续归类与回灌给模型。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_model_feedback(self) -> str:
        return f"[{self.code}] {self.message}"


@dataclass
class GuardedSQL:
    sql: str
    tables: list[str] = field(default_factory=list)
    limit: int = 0


def _cte_names(stmt: exp.Expression) -> set[str]:
    return {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE) if cte.alias_or_name}


def check(
    sql: str,
    *,
    dialect: str,
    allow_tables: set[str] | list[str],
    max_rows: int = 200,
) -> GuardedSQL:
    """校验并规范化一条只读 SQL。任何不合规都抛 GuardError。"""
    text = (sql or "").strip()
    if not text:
        raise GuardError("empty", "SQL 为空")

    read_dialect = DIALECT_BY_TYPE.get(dialect, dialect)
    try:
        statements = sqlglot.parse(text, read=read_dialect)
    except ParseError as exc:
        raise GuardError("syntax", f"解析失败：{exc}") from exc

    statements = [stmt for stmt in statements if stmt is not None]
    if len(statements) != 1:
        raise GuardError("multiple_statements", "只允许执行单条语句")
    stmt = statements[0]

    if not isinstance(stmt, (exp.Select, exp.Union)):
        raise GuardError("not_select", f"只允许 SELECT 查询，收到 {type(stmt).__name__}")

    for node in stmt.walk():
        if isinstance(node, FORBIDDEN):
            raise GuardError("forbidden_statement", f"包含被禁止的语句片段：{type(node).__name__}")
        if isinstance(node, exp.Anonymous) and str(node.this).upper() in BLOCKED_FUNCTIONS:
            raise GuardError("forbidden_function", f"包含被禁止的函数：{node.this}")

    normalized = stmt.sql(dialect=read_dialect)
    upper = normalized.upper()
    for name in BLOCKED_FUNCTIONS:
        if re.search(rf"\b{re.escape(name)}\s*\(", upper):
            raise GuardError("forbidden_function", f"包含被禁止的函数：{name}")

    allowed = {name.lower() for name in allow_tables}
    ctes = _cte_names(stmt)
    used = {table.name.lower() for table in stmt.find_all(exp.Table) if table.name}
    used -= ctes
    if allowed:
        extra = used - allowed
        if extra:
            raise GuardError("table_not_allowed", f"引用了未授权的表：{', '.join(sorted(extra))}")

    stmt = _enforce_limit(stmt, max_rows)
    return GuardedSQL(
        sql=stmt.sql(dialect=read_dialect),
        tables=sorted(used),
        limit=max_rows,
    )


def _enforce_limit(stmt: exp.Expression, max_rows: int) -> exp.Expression:
    """没有 LIMIT 就补上；LIMIT 过大改成上限；LIMIT 用不了（非字面量）就整体包一层。"""
    current = stmt.args.get("limit")
    if current is None:
        return stmt.limit(max_rows)

    expression = current.expression
    if isinstance(expression, exp.Literal) and expression.is_int:
        if int(expression.this) > max_rows:
            return stmt.limit(max_rows)
        return stmt

    # LIMIT 是参数/表达式时无法判定，包一层保证总行数受控
    return exp.select("*").from_(stmt.subquery("_bounded")).limit(max_rows)