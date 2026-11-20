"""只读问答接口：SSE 流式返回生成与执行过程。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.config import settings
from app.db import SessionLocal
from app.deps import get_current_user, get_model, get_session
from app.engine.llm import ChatModel
from app.engine.pipeline import Answer, answer_question
from app.models import Datasource, User
from app.schemas import ChatConfigOut, ChatFeedbackIn, ChatRequest
from app.security import get_secret_box

router = APIRouter(prefix="/chat", tags=["chat"])


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


async def _get_owned(session: AsyncSession, user: User, datasource_id: int) -> Datasource:
    ds = await session.get(Datasource, datasource_id)
    if ds is None or ds.workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "数据源不存在")
    return ds


def _snapshot(ds: Datasource) -> Datasource:
    """脱离 ORM 会话的副本：流式响应期间不能再依赖请求级 session。"""
    return Datasource(
        id=ds.id,
        workspace_id=ds.workspace_id,
        name=ds.name,
        type=ds.type,
        host=ds.host,
        port=ds.port,
        database=ds.database,
        username=ds.username,
        safety_level=ds.safety_level,
        is_prod=ds.is_prod,
    )


def _read_password(ds: Datasource) -> str:
    return get_secret_box().decrypt(ds.password_enc) if ds.password_enc else ""


@router.get("/config", response_model=ChatConfigOut)
async def chat_config(
    user: User = Depends(get_current_user),
    model: ChatModel = Depends(get_model),
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
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    model: ChatModel = Depends(get_model),
) -> StreamingResponse:
    stored = await _get_owned(session, user, body.datasource_id)
    password = _read_password(stored)
    ds = _snapshot(stored)
    actor_id, actor_name, workspace_id = user.id, user.username, user.workspace_id

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
            await _write_audit(actor_id, actor_name, workspace_id, ds, body.question, answer)
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


async def _write_audit(
    actor_id: int,
    actor_name: str,
    workspace_id: int,
    ds: Datasource,
    question: str,
    answer: Answer | None,
) -> None:
    try:
        async with SessionLocal() as session:
            await audit.record(
                session,
                workspace_id=workspace_id,
                action="chat.read",
                actor_id=actor_id,
                actor_name=actor_name,
                target_type="datasource",
                target_id=ds.id,
                result="ok" if (answer and answer.ok) else "error",
                detail={
                    "question": question[:500],
                    "sql": (answer.sql or "")[:2000] if answer else "",
                    "attempts": answer.attempts if answer else 0,
                    "tokens": answer.usage.total if answer else 0,
                    "elapsed_ms": answer.elapsed_ms if answer else 0,
                    "error": (answer.error or "")[:300] if answer else "",
                },
            )
    except Exception:  # noqa: BLE001 - 审计失败不能影响响应
        return


@router.post("/feedback", status_code=status.HTTP_202_ACCEPTED)
async def chat_feedback(
    body: ChatFeedbackIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """人工纠错入口：先落审计，示例库检索在 P3 接入。"""
    ds = await _get_owned(session, user, body.datasource_id)
    await audit.record(
        session,
        workspace_id=user.workspace_id,
        action="chat.feedback",
        actor_id=user.id,
        actor_name=user.username,
        target_type="datasource",
        target_id=ds.id,
        detail={
            "question": body.question[:500],
            "correct_sql": body.correct_sql[:4000],
            "note": body.note[:500],
        },
    )
    return {"status": "recorded"}