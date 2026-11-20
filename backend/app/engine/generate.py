"""两段式生成：先定口径与选表，再写 SQL。

一次直出 SQL 的准确率明显低于「先想清楚再写」，代价只是多一次十几毫秒的调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.engine.llm import ChatModel, LLMError, Usage, extract_json

PLAN_SYSTEM = """你是一名数据仓库分析师。根据下面的表结构与业务口径，判断回答用户问题需要哪些表、用哪些口径。
只输出一个 JSON 对象，不要解释、不要 Markdown 代码块：
{"tables": ["表名"], "metrics": ["指标 key"], "filters": ["过滤条件说明"], "time_range": "时间范围的解释", "clarification": "需要向用户确认的一句话"}

要求：
- tables 只能从给出的表里选，不能编造
- 只有缺少「唯一确定答案所必需」的信息时才反问（例如指代不明、口径冲突）；能用默认口径回答的，不要反问
- 问题没提时间范围时，默认统计全部历史数据，不要因此反问
- 反问只写一句，写进 clarification；其余字段尽力填
- 信息足够时 clarification 必须是空字符串
- 不要在这步写 SQL"""

WRITE_SYSTEM_TEMPLATE = """你是一名资深 SQL 工程师。根据表结构、业务口径和分析计划，写一条查询 SQL。
只输出一个 JSON 对象，不要解释、不要 Markdown 代码块：
{{"sql": "SELECT ...", "explain": "一句话说明这条 SQL 在算什么", "assumptions": ["你做过的假设"]}}

硬性要求：
- 只能写一条 SELECT（可以用 WITH 子句），禁止 INSERT/UPDATE/DELETE 或任何 DDL
- 只能使用给定表和给定列，禁止编造列名
- 不要写注释，不要写分号，不要在 JSON 之外输出任何文字
- 聚合列请起英文别名
- 今天是 {today}。遇到“本月/上季度/最近 7 天/去年”这类相对时间，先换算成具体日期区间
- 月份与季度统一用闭开区间比较：`created_at >= 'YYYY-MM-01' AND created_at < 'YYYY-MM-01'`（下个月 1 号）
- 禁止用 strftime 拼 "2026-Q03" 这种季度字符串：数据库没有这类格式串，会静默算错
- 一张订单可能有多条明细：按商品/品类统计金额时只能用 `order_items` 的 `quantity * unit_price`，
  不要对订单级金额（如 `orders.pay_amount`）做 SUM，否则会被明细行重复累加
- 不要使用数据库不存在的函数或语法"""

SUMMARIZE_SYSTEM = """你是数据分析助手。用一句中文回答用户的问题，必须包含关键数字，不要解释 SQL，不要罗列过程。
数字格式：计数用整数（如 1565，不要写成 1565.00），金额与比例保留两位小数。
如果结果为空、或关键字段是 NULL，直接说明没有匹配的数据，并给一个最可能的原因。"""


def write_system(today: date | None = None) -> str:
    return WRITE_SYSTEM_TEMPLATE.format(today=(today or date.today()).isoformat())


@dataclass
class Plan:
    tables: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    time_range: str = ""
    clarification: str = ""

    def render(self) -> str:
        lines = [f"- 需要用的表：{', '.join(self.tables) or '（未指定）'}"]
        if self.metrics:
            lines.append(f"- 指标：{', '.join(self.metrics)}")
        if self.filters:
            lines.append(f"- 过滤：{'; '.join(self.filters)}")
        if self.time_range:
            lines.append(f"- 时间范围：{self.time_range}")
        return "\n".join(lines)


@dataclass
class SQLDraft:
    sql: str
    explain: str = ""
    assumptions: list[str] = field(default_factory=list)


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


async def make_plan(
    question: str, context_text: str, model: ChatModel
) -> tuple[Plan, Usage]:
    user = f"## 用户问题\n{question}\n\n{context_text}"
    completion = await model.complete(PLAN_SYSTEM, user, max_tokens=500)
    data = extract_json(completion.text)
    plan = Plan(
        tables=_as_list(data.get("tables")),
        metrics=_as_list(data.get("metrics")),
        filters=_as_list(data.get("filters")),
        time_range=str(data.get("time_range") or ""),
        clarification=str(data.get("clarification") or "").strip(),
    )
    return plan, completion.usage


async def write_sql(
    question: str,
    plan: Plan,
    context_text: str,
    model: ChatModel,
    *,
    feedback: str | None = None,
) -> tuple[SQLDraft, Usage]:
    parts = [f"## 用户问题\n{question}", f"## 分析计划\n{plan.render()}", context_text]
    if feedback:
        parts.append(f"## 上一次失败的原因（必须修正）\n{feedback}")
    completion = await model.complete(write_system(), "\n\n".join(parts), max_tokens=800)
    data = extract_json(completion.text)
    sql = str(data.get("sql") or "").strip()
    if not sql:
        raise LLMError("模型没有给出 SQL")
    return (
        SQLDraft(
            sql=sql,
            explain=str(data.get("explain") or "").strip(),
            assumptions=_as_list(data.get("assumptions")),
        ),
        completion.usage,
    )


def render_result(columns: list[str], rows: list[list], total: int) -> str:
    shown = rows[:20]
    header = " | ".join(columns)
    lines = [header, "-" * min(len(header), 60)]
    for row in shown:
        lines.append(" | ".join("" if cell is None else str(cell) for cell in row))
    if total > len(shown):
        lines.append(f"...（共 {total} 行，这里只展示前 {len(shown)} 行）")
    return "\n".join(lines)


async def summarize(
    question: str,
    sql: str,
    columns: list[str],
    rows: list[list],
    total: int,
    model: ChatModel,
) -> tuple[str, Usage]:
    table = render_result(columns, rows, total)
    user = f"## 用户问题\n{question}\n\n## 执行的 SQL\n{sql}\n\n## 查询结果\n{table}"
    completion = await model.complete(SUMMARIZE_SYSTEM, user, max_tokens=220)
    return completion.text.strip(), completion.usage