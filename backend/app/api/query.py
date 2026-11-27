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
from app.quota import check_chat, hit_chat
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

    # 与 /chat/stream 共用同一份配额：一个工作空间一小时能问多少，两条通道合计
    limited = check_chat(principal.workspace_id)
    if limited is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"调用次数已达上限，请 {limited.retry_after} 秒后再试",
            headers={"Retry-After": str(limited.retry_after)},
        )
    hit_chat(principal.workspace_id)

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