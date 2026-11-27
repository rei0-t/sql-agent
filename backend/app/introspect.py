"""元数据抽取：把目标库的结构取成 schema 快照，供后续上下文装配使用。"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect

from app.config import settings
from app.dialects import get_dialect
from app.models import Datasource
from app.schemas import ColumnOut, SchemaOut, TableOut

logger = logging.getLogger(__name__)

MAX_TABLES = 200


async def _safe_row_counts(dialect, conn, tables: list[str]) -> dict[str, int]:
    """取行数是「锦上添花」：SQLite 会逐表 COUNT(*)（全表扫描），大表上能到秒级。

    所以给一个总预算，超时就放弃——行数只是给模型的量级提示，不值得阻塞首屏。
    """
    if not settings.schema_row_counts:
        return {}
    try:
        return await asyncio.wait_for(
            dialect.row_counts(conn, tables), timeout=settings.schema_row_counts_budget
        )
    except TimeoutError:
        logger.info("取行数超过 %.1fs，已跳过（数据源 %s）", settings.schema_row_counts_budget, dialect.name)
        return {}
    except Exception:  # noqa: BLE001 - 统计信息取不到不影响主流程
        logger.warning("取行数失败（数据源 %s）", dialect.name, exc_info=True)
        return {}


def _collect(sync_conn: Any) -> list[tuple[str, list[dict[str, Any]], list[str]]]:
    inspector = inspect(sync_conn)
    collected = []
    for name in inspector.get_table_names(schema=None)[:MAX_TABLES]:
        try:
            columns = inspector.get_columns(name, schema=None)
        except Exception:  # noqa: BLE001 - 个别视图/分区表可能取不到
            continue
        try:
            pk_columns = inspector.get_pk_constraint(name, schema=None).get("constrained_columns") or []
        except Exception:  # noqa: BLE001
            pk_columns = []
        collected.append((name, columns, list(pk_columns)))
    return collected


async def introspect(ds: Datasource, password: str) -> SchemaOut:
    dialect = get_dialect(ds.type)
    engine = dialect.create_engine(ds, password)
    try:
        async with engine.connect() as conn:
            raw = await conn.run_sync(_collect)
            counts = await _safe_row_counts(dialect, conn, [name for name, _, _ in raw])
    finally:
        await engine.dispose()

    tables: list[TableOut] = []
    for name, columns, pk_columns in raw:
        pk_set = {str(col) for col in pk_columns}
        tables.append(
            TableOut(
                name=name,
                row_count_estimate=counts.get(name.lower()),
                columns=[
                    ColumnOut(
                        name=str(col["name"]),
                        data_type=str(col.get("type")),
                        nullable=bool(col.get("nullable", True)),
                        primary_key=str(col["name"]) in pk_set,
                        comment=(col.get("comment") or None),
                    )
                    for col in columns
                ],
            )
        )

    return SchemaOut(
        datasource_id=ds.id,
        fetched_at=datetime.now(UTC),
        tables=tables,
    )