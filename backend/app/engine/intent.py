"""意图拦截：只读系统必须拒绝"改数据"的请求，而且要拒绝得**明确**。

为什么需要它（真实事故）：
    用户问「帮我把测试数据删掉」，闸门确实挡住了写操作，但模型为了"完成任务"
    编了一条 SELECT 去统计被删数据，然后总结成
    「已删除测试数据，共清理 26 万」——**数据一个字没动，结论却在撒谎**。

    只读系统最危险的失败不是"做不了"，而是"假装做了"。
    所以要在**生成 SQL 之前**就把写意图拦下来，连模型都不必调用。

判定策略（宁可保守，但不要过度拦截）：
- 明确祈使句（帮我删/请清空/把…删掉）→ 拦
- 句首就是破坏性动词（删除 xxx、清空表）→ 拦
- 含"已删除/删除的/被删"这类**定语或被动**的读查询 → 放行
"""

from __future__ import annotations

import re

# 破坏性动作：只列会造成数据变更或结构变更的
MUTATING_VERBS = (
    "删除",
    "删掉",
    "删了",
    "移除",
    "清空",
    "清除",
    "更新",
    "修改",
    "改成",
    "插入",
    "新增",
    "写入",
    "导入",
    "建表",
    "删表",
    "改表",
    "truncate",
    "drop",
    "delete",
    "update",
    "insert",
    "alter",
)

# 祈使标记：出现在动词前面，说明用户在下命令
IMPERATIVE_MARKERS = ("帮我", "请你", "请", "麻烦", "给我", "把", "替我", "帮忙")

# 读意图标记：出现这些词通常是在问情况，不是在下命令
READ_MARKERS = ("多少", "哪些", "几个", "几条", "统计", "查询", "查看", "是什么", "占比", "趋势")


def detect_mutation(question: str) -> str | None:
    """命中写意图时返回命中的动词，否则返回 None。"""
    text = (question or "").strip().lower()
    if not text:
        return None

    # 被动/定语用法放行：「已删除的订单有多少」是在问数据，不是要删数据
    if re.search(r"(已|被|待|将要|准备)(删除|移除|清除)", text):
        return None

    hit = next((verb for verb in MUTATING_VERBS if verb in text), None)
    if hit is None:
        return None

    position = text.index(hit)
    has_imperative = any(marker in text[: position + len(hit)] for marker in IMPERATIVE_MARKERS)
    at_start = position <= 2
    is_question = any(marker in text for marker in READ_MARKERS)

    if (has_imperative or at_start) and not is_question:
        return hit
    return None


def refusal(verb: str, table_hint: str = "") -> str:
    """给用户看的拒绝话术 —— 说清能力边界，并给出可执行的替代问法。"""
    hint = f"，目标可能是 {table_hint}" if table_hint else ""
    return (
        f"我只做只读查询，不能执行「{verb}」这类会改动数据的操作{hint}。"
        "如果想看数据情况，可以换个问法，比如「一共有多少条订单」「哪些订单已经退款」。"
    )