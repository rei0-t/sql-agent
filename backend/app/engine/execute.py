"""只读执行器：超时、行数上限、结果规范化。

连接本身来自 `dialects`，SQLite 走 `mode=ro`，MySQL/PG 用只读账号，
所以这里只做资源保护，不承担权限控制。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import time as dtime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.dialects import get_dialect
from app.models import Datasource

logger = logging.getLogger(__name__)


class ExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_model_feedback(self) -> str:
        return f"[{self.code}] {self.message}"


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    elapsed_ms: int = 0


def jsonable(value: Any) -> Any:
    """把驱动返回值转成能直接进 JSON 的类型。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, dtime)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return base64.b64encode(raw).decode("ascii") if len(raw) <= 64 else f"<{len(raw)} bytes>"
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _classify(exc: Exception) -> ExecutionError:
    message = " ".join(str(exc).split())
    if len(message) > 300:
        message = message[:300] + "…"
    lowered = message.lower()
    if "no such column" in lowered or "unknown column" in lowered or "does not exist" in lowered:
        return ExecutionError("unknown_column", message)
    if "no such table" in lowered or "doesn't exist" in lowered:
        return ExecutionError("unknown_table", message)
    if "syntax" in lowered:
        return ExecutionError("syntax", message)
    if "ambiguous" in lowered:
        return ExecutionError("ambiguous", message)
    return ExecutionError("execution", f"{type(exc).__name__}: {message}")


async def _apply_timeout(conn: Any, ds_type: str, timeout_seconds: int) -> None:
    """尽量让数据库自己超时，这样报错可读、也能被归类后回灌给模型。

    这只是"锦上添花"：MariaDB 用 max_statement_time，老的 MySQL 没有这个变量，
    设置失败不该让整条查询挂掉——进程侧的 asyncio.wait_for 仍然兜底。
    """
    statement = {
        "postgres": f"SET statement_timeout = {timeout_seconds * 1000}",
        "mysql": f"SET SESSION MAX_EXECUTION_TIME = {timeout_seconds * 1000}",
    }.get(ds_type)
    if statement is None:
        return
    try:
        await conn.execute(text(statement))
    except Exception:  # noqa: BLE001 - 方言差异，降级为仅靠进程侧超时
        logger.debug("设置查询超时失败（%s），改由进程侧超时兜底", ds_type, exc_info=True)


async def run_select(
    ds: Datasource,
    password: str,
    sql: str,
    *,
    max_rows: int = 200,
    timeout: int = 10,
) -> QueryResult:
    dialect = get_dialect(ds.type)
    engine = dialect.create_engine(ds, password, writable=False)
    started = time.perf_counter()

    async def _run() -> QueryResult:
        async with engine.connect() as conn:
            if ds.type in {"postgres", "mysql"}:
                await _apply_timeout(conn, ds.type, timeout)
            result = await conn.execute(text(sql))
            columns = list(result.keys())
            fetched = result.fetchmany(max_rows + 1)
            truncated = len(fetched) > max_rows
            rows = [list(row) for row in fetched[:max_rows]]
            return QueryResult(
                columns=columns,
                rows=rows,
                truncated=truncated,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

    try:
        result = await asyncio.wait_for(_run(), timeout=timeout + 2)
        result.rows = [[jsonable(cell) for cell in row] for row in result.rows]
        return result
    except TimeoutError as exc:
        raise ExecutionError("timeout", f"查询超过 {timeout} 秒被中断") from exc
    except ExecutionError:
        raise
    except Exception as exc:  # noqa: BLE001 - 驱动异常统一归类
        raise _classify(exc) from exc
    finally:
        await engine.dispose()


async def count_rows(ds: Datasource, password: str, sql: str, *, timeout: int = 10) -> int | None:
    """给变更通道预留：拿 COUNT(*) 估影响面（P2 使用）。"""
    wrapped = f"SELECT COUNT(*) FROM ({sql}) AS _c"
    result = await run_select(ds, password, wrapped, max_rows=1, timeout=timeout)
    if result.rows and result.rows[0]:
        value = result.rows[0][0]
        return int(value) if isinstance(value, (int, float)) else None
    return None