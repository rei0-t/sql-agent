"""只读问答接口：SSE 流式返回生成与执行过程。

工程要点：
- queue + 独立 task：让「生成」和「发送」并行，否则模型思考的十秒里前端一个字节都收不到。
- store.snapshot：流式期间请求级 session 已关闭，必须用脱离会话的副本。
- X-Accel-Buffering: no：避免 Nginx 缓冲导致「卡住十秒后一次性刷出」。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Auditor
from app.config import settings
from app.deps import (
    Principal,
    get_auditor,
    get_model_for_principal,
    get_principal,
    get_session,
)
from app.engine.llm import ChatModel
from app.engine.pipeline import Answer, answer_question
from app.schemas import ChatConfigOut, ChatFeedbackIn, ChatRequest
from app.store import owned_datasource, read_password, snapshot

router = APIRouter(prefix="/chat", tags=["chat"])


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@router.get("/config", response_model=ChatConfigOut)
async def chat_config(
    model: ChatModel = Depends(get_model_for_principal),
) -> ChatConfigOut:
    return ChatConfigOut(
        model=getattr(model, "name", settings.llm_model),
        configured=bool(getattr(model, "configured", False)),
        max_rows=settings.read_max_rows,
        query_timeout=settings.query_timeout,
        max_repair=settings.max_repair,
    )


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    model: ChatModel = Depends(get_model_for_principal),
    auditor: Auditor = Depends(get_auditor),
) -> StreamingResponse:
    stored = await owned_datasource(session, principal.workspace_id, body.datasource_id)
    password = read_password(stored)
    ds = snapshot(stored)

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def emit(event: str, data: dict[str, Any]) -> None:
        await queue.put(_sse(event, data))

    async def worker() -> None:
        answer: Answer | None = None
        try:
            answer = await answer_question(ds, password, body.question, model, emit=emit)
            await queue.put(
                _sse(
                    "done",
                    {
                        "ok": answer.ok,
                        "attempts": answer.attempts,
                        "elapsed_ms": answer.elapsed_ms,
                        "tokens": answer.usage.total,
                        "model": answer.model,
                        "error": answer.error,
                        "clarification": answer.clarification,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 - 兜底，保证前端一定收到终态
            await queue.put(_sse("error", {"detail": str(exc)[:300]}))
            await queue.put(_sse("done", {"ok": False, "error": "内部错误"}))
        finally:
            await auditor.log(
                "chat.read",
                target_type="datasource",
                target_id=ds.id,
                result="ok" if (answer and answer.ok) else "error",
                detail={
                    "question": body.question[:500],
                    "sql": (answer.sql or "")[:2000] if answer else "",
                    "attempts": answer.attempts if answer else 0,
                    "tokens": answer.usage.total if answer else 0,
                    "elapsed_ms": answer.elapsed_ms if answer else 0,
                    "error": (answer.error or "")[:300] if answer else "",
                },
            )
            await queue.put(None)

    task = asyncio.create_task(worker())

    async def event_source():
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/feedback", status_code=202)
async def chat_feedback(
    body: ChatFeedbackIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    auditor: Auditor = Depends(get_auditor),
) -> dict[str, str]:
    """人工纠错入口：先落审计，示例库检索在 P3 接入。"""
    ds = await owned_datasource(session, principal.workspace_id, body.datasource_id)
    await auditor.log(
        "chat.feedback",
        target_type="datasource",
        target_id=ds.id,
        detail={
            "question": body.question[:500],
            "correct_sql": body.correct_sql[:4000],
            "note": body.note[:500],
        },
    )
    return {"status": "recorded"}