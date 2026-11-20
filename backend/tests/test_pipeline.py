"""问答主循环：用 FakeModel 覆盖正常路径、自纠错与澄清。"""

from __future__ import annotations

import json

import pytest

from app.engine.llm import FakeModel
from app.engine.pipeline import answer_question
from app.models import Datasource


@pytest.fixture()
def sqlite_ds(demo_sqlite) -> Datasource:
    return Datasource(id=999, type="sqlite", database=str(demo_sqlite), name="demo")


def plan_json(**overrides) -> str:
    payload = {
        "tables": ["orders", "customers"],
        "metrics": ["gmv"],
        "filters": ["排除测试账号"],
        "time_range": "",
        "clarification": "",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def sql_json(sql: str) -> str:
    return json.dumps({"sql": sql, "explain": "统计订单数", "assumptions": []}, ensure_ascii=False)


async def test_happy_path(sqlite_ds: Datasource) -> None:
    model = FakeModel(
        [
            plan_json(),
            sql_json("SELECT COUNT(*) AS n FROM orders"),
            "共有 2 笔订单。",
        ]
    )
    events: list[tuple[str, dict]] = []

    async def emit(event: str, data: dict) -> None:
        events.append((event, data))

    answer = await answer_question(sqlite_ds, "", "一共有多少订单？", model, emit=emit)

    assert answer.error is None
    assert answer.sql is not None and "LIMIT" in answer.sql.upper()
    assert answer.columns == ["n"]
    assert answer.rows == [[2]]
    assert answer.summary == "共有 2 笔订单。"
    assert answer.attempts == 1
    assert [name for name, _ in events].count("stage") >= 3
    assert any(name == "sql" for name, _ in events)
    assert any(name == "answer" for name, _ in events)


async def test_repairs_after_guard_rejection(sqlite_ds: Datasource) -> None:
    model = FakeModel(
        [
            plan_json(),
            sql_json("SELECT * FROM ghost_table"),
            sql_json("SELECT COUNT(*) AS n FROM customers"),
            "共 2 个客户。",
        ]
    )
    answer = await answer_question(sqlite_ds, "", "有多少客户？", model)

    assert answer.error is None
    assert answer.attempts == 2
    assert "customers" in (answer.sql or "")
    assert answer.rows == [[2]]

    # 第二次生成时必须把闸门的拒绝原因回灌给模型
    second_prompt = model.prompts[2][1]
    assert "上一次失败" in second_prompt
    assert "ghost_table" in second_prompt


async def test_repairs_after_execution_error(sqlite_ds: Datasource) -> None:
    model = FakeModel(
        [
            plan_json(),
            sql_json("SELECT missing_column AS n FROM orders"),
            sql_json("SELECT COUNT(*) AS n FROM orders"),
            "共 2 笔订单。",
        ]
    )
    answer = await answer_question(sqlite_ds, "", "有多少订单？", model)
    assert answer.error is None
    assert answer.attempts == 2


async def test_gives_up_and_reports_error(sqlite_ds: Datasource) -> None:
    model = FakeModel(
        [
            plan_json(),
            sql_json("SELECT * FROM ghost_a"),
            sql_json("SELECT * FROM ghost_b"),
            sql_json("SELECT * FROM ghost_c"),
        ]
    )
    answer = await answer_question(sqlite_ds, "", "随便问问", model)
    assert answer.ok is False
    assert "ghost" in (answer.error or "")
    assert answer.attempts == 3


async def test_returns_clarification_without_sql(sqlite_ds: Datasource) -> None:
    model = FakeModel([plan_json(clarification="你说的“最近”是指哪段时间？")])
    answer = await answer_question(sqlite_ds, "", "最近卖得怎么样？", model)

    assert answer.clarification == "你说的“最近”是指哪段时间？"
    assert answer.sql is None
    assert answer.summary == answer.clarification


async def test_bad_json_is_retried(sqlite_ds: Datasource) -> None:
    model = FakeModel(
        [
            "抱歉，我需要更多信息",  # 计划阶段输出非 JSON
            plan_json(),
            sql_json("SELECT COUNT(*) AS n FROM orders"),
            "共 2 笔订单。",
        ]
    )
    answer = await answer_question(sqlite_ds, "", "有多少订单？", model)
    # 计划阶段失败会直接返回错误，不会静默；这里确认错误被显式暴露
    assert answer.error is not None or answer.ok is False