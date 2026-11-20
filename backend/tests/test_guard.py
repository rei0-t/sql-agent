"""只读闸门：该放行的放行，该拦死的一条都不能过。"""

from __future__ import annotations

import pytest

from app.engine.guard import GuardError, check

TABLES = {"orders", "customers", "products"}


def test_plain_select_gets_limit() -> None:
    guarded = check("SELECT id FROM orders", dialect="sqlite", allow_tables=TABLES, max_rows=100)
    assert "LIMIT 100" in guarded.sql.upper()
    assert guarded.tables == ["orders"]


def test_existing_small_limit_is_kept() -> None:
    guarded = check(
        "SELECT id FROM orders LIMIT 5", dialect="sqlite", allow_tables=TABLES, max_rows=100
    )
    assert "LIMIT 5" in guarded.sql.upper()


def test_oversized_limit_is_clamped() -> None:
    guarded = check(
        "SELECT id FROM orders LIMIT 999999", dialect="sqlite", allow_tables=TABLES, max_rows=100
    )
    assert "LIMIT 100" in guarded.sql.upper()
    assert "999999" not in guarded.sql


def test_join_and_cte_are_allowed() -> None:
    sql = """
        WITH paid AS (SELECT id, customer_id FROM orders WHERE status = 'paid')
        SELECT c.id, COUNT(*) FROM paid p JOIN customers c ON c.id = p.customer_id GROUP BY c.id
    """
    guarded = check(sql, dialect="sqlite", allow_tables=TABLES, max_rows=100)
    assert set(guarded.tables) == {"orders", "customers"}
    assert "LIMIT 100" in guarded.sql.upper()


def test_union_is_allowed() -> None:
    sql = "SELECT id FROM orders UNION SELECT id FROM products"
    guarded = check(sql, dialect="sqlite", allow_tables=TABLES, max_rows=50)
    assert "LIMIT 50" in guarded.sql.upper()


@pytest.mark.parametrize(
    "sql,code",
    [
        ("DELETE FROM orders", "not_select"),
        ("UPDATE orders SET status = 'x'", "not_select"),
        ("INSERT INTO orders (id) VALUES (1)", "not_select"),
        ("DROP TABLE orders", "not_select"),
        ("ALTER TABLE orders ADD COLUMN x INT", "not_select"),
        ("PRAGMA table_info(orders)", "not_select"),
        ("ATTACH DATABASE 'x.db' AS x", "not_select"),
        ("SELECT 1; DELETE FROM orders", "multiple_statements"),
        ("SELECT * FROM orders; SELECT * FROM customers", "multiple_statements"),
        ("SELECT * FROM secrets", "table_not_allowed"),
        # SELECT ... INTO 是 SELECT 语法，但带 INTO 节点，按语句片段拦截
        ("SELECT * INTO backup FROM orders", "forbidden_statement"),
        ("SELECT LOAD_FILE('/etc/passwd')", "forbidden_function"),
        ("SELECT * FROM orders WHERE id = 1 OR SLEEP(10)", "forbidden_function"),
        ("", "empty"),
        ("SELECT FROM WHERE", "syntax"),
    ],
)
def test_rejections(sql: str, code: str) -> None:
    with pytest.raises(GuardError) as exc:
        check(sql, dialect="sqlite", allow_tables=TABLES, max_rows=100)
    assert exc.value.code == code


def test_guard_error_is_feedable_to_model() -> None:
    with pytest.raises(GuardError) as exc:
        check("SELECT * FROM secrets", dialect="sqlite", allow_tables=TABLES)
    assert exc.value.to_model_feedback().startswith("[table_not_allowed]")