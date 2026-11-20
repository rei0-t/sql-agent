"""元数据抽取：把目标库的结构取成 schema 快照，供后续上下文装配使用。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect

from app.dialects import get_dialect
from app.models import Datasource
from app.schemas import ColumnOut, SchemaOut, TableOut

MAX_TABLES = 200


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
            counts = await dialect.row_counts(conn, [name for name, _, _ in raw])
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