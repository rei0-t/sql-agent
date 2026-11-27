"""面向开发者的查询接口：一次调用，直接拿 JSON 结果。

与 /chat/stream 的区别：不要流式、不要会话，只要「问题进、结构化结果出」，
方便脚本、CI、定时任务和内嵌到别的系统里。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Auditor
from app.deps import (
    Principal,
    get_auditor,
    get_model_for_principal,
    get_principal,
    get_session,
)
from app.engine.llm import ChatModel
from app.engine.pipeline import answer_question
from app.quota import consume
from app.schemas import QueryIn, QueryOut
from app.store import owned_datasource, read_password

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryOut)
async def run_query(
    body: QueryIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    model: ChatModel = Depends(get_model_for_principal),
    auditor: Auditor = Depends(get_auditor),
) -> QueryOut:
    ds = await owned_datasource(session, principal.workspace_id, body.datasource_id)

    # 没配 Key 是配置故障：先拒绝，别浪费用户的额度
    if not getattr(model, "configured", True):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "站点还没有配置模型密钥，请联系管理员",
        )

    # 与 /chat/stream 共用同一个额度账本
    await consume(session, principal)

    answer = await answer_question(ds, read_password(ds), body.question, model)

    await auditor.log(
        "api.query",
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

    return QueryOut.model_validate(answer, from_attributes=True)