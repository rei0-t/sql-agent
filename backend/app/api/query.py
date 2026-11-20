"""面向开发者的查询接口：一次调用，直接拿 JSON 结果。

与 /chat/stream 的区别：不要流式、不要会话，只要「问题进、结构化结果出」，
方便脚本、CI、定时任务和内嵌到别的系统里。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import SessionLocal
from app.deps import Principal, get_model_for_principal, get_principal, get_session
from app.engine.llm import ChatModel
from app.engine.pipeline import answer_question
from app.models import Datasource
from app.schemas import QueryIn, QueryOut
from app.security import get_secret_box

router = APIRouter(tags=["query"])


async def _load_datasource(session: AsyncSession, workspace_id: int, ds_id: int) -> Datasource:
    ds = await session.get(Datasource, ds_id)
    if ds is None or ds.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "数据源不存在")
    return ds


def _read_password(ds: Datasource) -> str:
    return get_secret_box().decrypt(ds.password_enc) if ds.password_enc else ""


@router.post("/query", response_model=QueryOut)
async def run_query(
    body: QueryIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    model: ChatModel = Depends(get_model_for_principal),
) -> QueryOut:
    ds = await _load_datasource(session, principal.workspace_id, body.datasource_id)
    answer = await answer_question(ds, _read_password(ds), body.question, model)

    async with SessionLocal() as audit_session:
        await audit.record(
            audit_session,
            workspace_id=principal.workspace_id,
            action="api.query",
            actor_id=principal.actor_id,
            actor_name=principal.actor_name,
            target_type="datasource",
            target_id=ds.id,
            result="ok" if answer.ok else "error",
            detail={
                "via": principal.via,
                "question": body.question[:500],
                "sql": (answer.sql or "")[:2000],
                "attempts": answer.attempts,
                "tokens": answer.usage.total,
                "elapsed_ms": answer.elapsed_ms,
                "error": (answer.error or "")[:300],
            },
        )

    return QueryOut(
        question=answer.question,
        sql=answer.sql,
        columns=answer.columns,
        rows=answer.rows,
        summary=answer.summary,
        explain=answer.explain,
        tables=answer.tables,
        attempts=answer.attempts,
        truncated=answer.truncated,
        elapsed_ms=answer.elapsed_ms,
        tokens=answer.usage.total,
        model=answer.model,
        error=answer.error,
        clarification=answer.clarification,
    )