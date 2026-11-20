"""只读问答主循环：装配 → 计划 → 生成 → 闸门 → 执行 → 自纠错 → 结论。

一轮问答最多重写 `settings.max_repair` 次，每次把闸门或数据库的错误按类型回灌。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.config import settings
from app.engine.context import build_context
from app.engine.execute import ExecutionError, run_select
from app.engine.generate import SQLDraft, make_plan, summarize, write_sql
from app.engine.guard import GuardError, check
from app.engine.llm import ChatModel, LLMError, Usage
from app.engine.semantics import load_semantics
from app.models import Datasource

Emit = Callable[[str, dict], Awaitable[None]]


@dataclass
class Answer:
    question: str = ""
    sql: str | None = None
    explain: str = ""
    assumptions: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    truncated: bool = False
    summary: str = ""
    tables: list[str] = field(default_factory=list)
    attempts: int = 0
    elapsed_ms: int = 0
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    error: str | None = None
    clarification: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.sql is not None


async def _noop(_: str, __: dict) -> None:
    return None


async def answer_question(
    ds: Datasource,
    password: str,
    question: str,
    model: ChatModel,
    *,
    emit: Emit | None = None,
) -> Answer:
    emit = emit or _noop
    started = time.perf_counter()
    usage = Usage()
    answer = Answer(question=question, model=getattr(model, "name", ""))

    semantics = load_semantics()
    await emit("stage", {"stage": "context"})
    try:
        context = await build_context(ds, password, question, semantics_text=semantics.render())
    except Exception as exc:  # noqa: BLE001 - 读结构失败就是数据源问题
        answer.error = f"读取表结构失败：{exc}"
        answer.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return answer

    answer.tables = context.tables

    try:
        await emit("stage", {"stage": "planning"})
        plan, plan_usage = await make_plan(question, context.text, model)
        usage.merge(plan_usage)
    except LLMError as exc:
        answer.error = str(exc)
        answer.elapsed_ms = int((time.perf_counter() - started) * 1000)
        answer.usage = usage
        return answer

    if plan.clarification:
        answer.clarification = plan.clarification
        answer.summary = plan.clarification
        answer.elapsed_ms = int((time.perf_counter() - started) * 1000)
        answer.usage = usage
        await emit("clarify", {"question": plan.clarification})
        return answer

    feedback: str | None = None
    draft: SQLDraft | None = None
    result = None

    for attempt in range(1, settings.max_repair + 1):
        answer.attempts = attempt
        try:
            await emit("stage", {"stage": "generating", "attempt": attempt})
            draft, gen_usage = await write_sql(
                question, plan, context.text, model, feedback=feedback
            )
            usage.merge(gen_usage)
        except LLMError as exc:
            feedback = f"[llm] {exc}\n请只输出合法 JSON。"
            await emit("error", {"attempt": attempt, "detail": str(exc)})
            continue

        try:
            guarded = check(
                draft.sql,
                dialect=ds.type,
                allow_tables=set(context.candidate_tables),
                max_rows=settings.read_max_rows,
            )
        except GuardError as exc:
            feedback = exc.to_model_feedback()
            await emit("error", {"attempt": attempt, "code": exc.code, "detail": exc.message})
            continue

        answer.sql = guarded.sql
        answer.explain = draft.explain
        answer.assumptions = draft.assumptions
        await emit("sql", {"sql": guarded.sql, "attempt": attempt, "explain": draft.explain})

        try:
            await emit("stage", {"stage": "executing", "attempt": attempt})
            result = await run_select(
                ds,
                password,
                guarded.sql,
                max_rows=settings.read_max_rows,
                timeout=settings.query_timeout,
            )
        except ExecutionError as exc:
            feedback = exc.to_model_feedback()
            await emit("error", {"attempt": attempt, "code": exc.code, "detail": exc.message})
            continue
        except Exception as exc:  # noqa: BLE001 - 连接层的意外错误
            feedback = f"[execution] {exc}"[:400]
            await emit("error", {"attempt": attempt, "detail": str(exc)[:200]})
            continue

        break

    answer.usage = usage
    answer.elapsed_ms = int((time.perf_counter() - started) * 1000)

    if result is None:
        answer.error = feedback or "没有生成可执行的 SQL"
        return answer

    answer.columns = result.columns
    answer.rows = result.rows
    answer.truncated = result.truncated
    await emit(
        "rows",
        {
            "columns": result.columns,
            "rows": result.rows,
            "truncated": result.truncated,
            "elapsed_ms": result.elapsed_ms,
        },
    )

    try:
        await emit("stage", {"stage": "summarizing"})
        summary, sum_usage = await summarize(
            question, answer.sql or "", result.columns, result.rows, len(result.rows), model
        )
        usage.merge(sum_usage)
        answer.summary = summary
    except LLMError:
        answer.summary = ""

    answer.usage = usage
    answer.elapsed_ms = int((time.perf_counter() - started) * 1000)
    await emit(
        "answer",
        {
            "text": answer.summary,
            "attempts": answer.attempts,
            "elapsed_ms": answer.elapsed_ms,
            "tokens": usage.total,
        },
    )
    return answer