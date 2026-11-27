"""写意图拦截。

真实事故：用户问「帮我把测试数据删掉」，闸门挡住了写操作，
但模型编了一条 SELECT 去"统计被删数据"，然后总结成「已删除…共清理 26 万」。
数据一个字没动，结论却在撒谎 —— 只读系统最危险的失败是"假装做了"。
"""

from __future__ import annotations

import pytest

from app.engine.intent import detect_mutation


@pytest.mark.parametrize(
    "question",
    [
        "帮我把测试数据删掉",
        "请清空 orders 表",
        "把 2025 年的订单都删了",
        "更新一下客户的手机号",
        "插入一条测试订单",
        "drop table orders",
        "truncate orders",
        "删除所有退款记录",
        "麻烦清除测试账号的数据",
    ],
)
def test_detects_mutations(question: str) -> None:
    assert detect_mutation(question) is not None


@pytest.mark.parametrize(
    "question",
    [
        "一共有多少笔订单",
        "已删除的订单有多少条",          # 定语用法，问的是数据
        "哪些订单被清除了",              # 被动用法
        "退款率最高的月份是哪个月",
        "2026 年第三季度华东区的 GMV 是多少",
        "删除状态的订单占比是多少",      # "删除"是状态名
    ],
)
def test_allows_read_questions(question: str) -> None:
    assert detect_mutation(question) is None


def test_refusal_message_is_actionable() -> None:
    from app.engine.intent import refusal

    text = refusal("删除")
    assert "只读" in text
    assert "换个问法" in text