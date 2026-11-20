"""只读执行器：行数上限、结果规范化、错误归类。"""

from __future__ import annotations

import pytest

from app.engine.execute import ExecutionError, jsonable, run_select
from app.models import Datasource


@pytest.fixture()
def sqlite_ds(demo_sqlite) -> Datasource:
    return Datasource(id=999, type="sqlite", database=str(demo_sqlite), name="demo")


async def test_select_returns_columns_and_rows(sqlite_ds: Datasource) -> None:
    result = await run_select(sqlite_ds, "", "SELECT id, name FROM customers ORDER BY id")
    assert result.columns == ["id", "name"]
    assert len(result.rows) == 2
    assert result.truncated is False
    assert result.rows[0][0] == 1


async def test_row_cap_truncates(sqlite_ds: Datasource) -> None:
    result = await run_select(sqlite_ds, "", "SELECT id FROM customers", max_rows=1)
    assert len(result.rows) == 1
    assert result.truncated is True


async def test_unknown_column_is_classified(sqlite_ds: Datasource) -> None:
    with pytest.raises(ExecutionError) as exc:
        await run_select(sqlite_ds, "", "SELECT nope FROM customers")
    assert exc.value.code == "unknown_column"


async def test_unknown_table_is_classified(sqlite_ds: Datasource) -> None:
    with pytest.raises(ExecutionError) as exc:
        await run_select(sqlite_ds, "", "SELECT * FROM ghost")
    assert exc.value.code == "unknown_table"


async def test_read_only_connection_blocks_writes(sqlite_ds: Datasource) -> None:
    """即使闸门被绕过，连接本身也写不进去。"""
    with pytest.raises(ExecutionError):
        await run_select(sqlite_ds, "", "UPDATE customers SET name = 'x' WHERE id = 1")
    result = await run_select(sqlite_ds, "", "SELECT name FROM customers WHERE id = 1")
    assert result.rows[0][0] == "张三"


def test_jsonable_handles_common_types() -> None:
    from datetime import date, datetime
    from decimal import Decimal

    assert jsonable(Decimal("1.50")) == 1.5
    assert jsonable(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05"
    assert jsonable(date(2026, 1, 2)) == "2026-01-02"
    assert jsonable(b"abc") == "YWJj"
    assert jsonable(None) is None