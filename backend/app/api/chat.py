"""只读问答接口：SSE 流式返回生成与执行过程。

工程要点：
- queue + 独立 task：让「生成」和「发送」并行，否则模型思考的十秒里前端一个字节都收不到。
- 客户端断开时**不取消** worker：取消会打断审计写入，让中途关页面的请求从审计里消失。
- store.snapshot：流式期间请求级 session 已关闭，必须用脱离会话的副本。
- X-Accel-Buffering: no：避免 Nginx 缓冲导致「卡住十秒后一次性刷出」。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Auditor
from app.config import settings
from app.deps import (
    Principal,
    get_auditor,
    get_principal,
    get_session,
    model_for_request,
    resolve_profile,
)
from app.engine.llm import ChatModel
from app.engine.pipeline import Answer, answer_question
from app.quota import consume, limit, profile_has_key, remaining_for
from app.schemas import ChatConfigOut, ChatFeedbackIn, ChatRequest
from app.store import owned_datasource, read_password, snapshot

router = APIRouter(prefix="/chat", tags=["chat"])

logger = logging.getLogger(__name__)


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@router.get("/config", response_model=ChatConfigOut)
async def chat_config(
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> ChatConfigOut:
    """对话页初始化信息。

    **不回传站点的 Base URL 与真实模型名**：试用用户只该看到"平台额度 · 还剩 N 次"。
    """
    profile = await resolve_profile(session, principal.workspace_id)
    byok = await profile_has_key(session, principal.workspace_id)
    remaining_questions = await remaining_for(session, principal, byok=byok)
    using_platform = profile is None
    label = "平台额度（试用）" if using_platform else (profile.label or "我的模型")
    # 测试会注入 app.state.llm；此时界面该显示的就是它，而不是环境变量里的名字
    override = getattr(request.app.state, "llm", None)
    platform_model = getattr(override, "name", None) or settings.llm_model
    return ChatConfigOut(
        model_label=label,
        model_profile_id=None if using_platform else profile.id,
        using_platform=using_platform,
        # 访客看不到站点的真实模型名；管理员与自建档位可见
        model=(
            (profile.model or "") if not using_platform
            else (platform_model if principal.is_admin else "")
        ),
        configured=bool(settings.llm_api_key) or byok,
        max_rows=settings.read_max_rows,
        query_timeout=settings.query_timeout,
        max_repair=settings.max_repair,
        remaining_questions=remaining_questions,
        quota_total=limit() or None,
    )


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    auditor: Auditor = Depends(get_auditor),
) -> StreamingResponse:
    stored = await owned_datasource(session, principal.workspace_id, body.datasource_id)
    model: ChatModel = await model_for_request(
        request, session, principal.workspace_id, body.model_profile_id
    )
    password = read_password(stored)
    ds = snapshot(stored)

    # 站点没配 Key 属于配置故障，不是用户的问题：在扣额度**之前**就拒绝，
    # 否则用户白丢一次机会，还会以为是自己用错了。
    if not getattr(model, "configured", True):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "站点还没有配置模型密钥，请联系管理员（或在「设置」里填自己的 Key）",
        )

    # 额度：用公共 Key 对外开放时，这层是唯一防刷的手段
    try:
        remaining = await consume(session, principal, body.model_profile_id)
    except HTTPException as exc:
        await auditor.log(
            "chat.read",
            target_type="datasource",
            target_id=body.datasource_id,
            result="denied",
            detail={"reason": "quota_exhausted", "detail": exc.detail},
        )
        raise

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
                        # 问题里命中了可疑话术：不拦截，但让调用方知道
                        "injection_flags": answer.injection_flags,
                        # 剩余额度（None = 不限）；前端据此更新提示
                        "remaining": remaining,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 - 兜底，保证前端一定收到终态
            # 也要落服务端日志：客户端可能已经断开，只塞进 SSE 等于没记
            logger.warning("问答失败（datasource=%s）：%s", ds.id, exc, exc_info=True)
            await queue.put(_sse("error", {"detail": str(exc)[:300]}))
            await queue.put(_sse("done", {"ok": False, "error": "内部错误"}))
        finally:
            detail = {
                "question": body.question[:500],
                "sql": (answer.sql or "")[:2000] if answer else "",
                "attempts": answer.attempts if answer else 0,
                "tokens": answer.usage.total if answer else 0,
                "elapsed_ms": answer.elapsed_ms if answer else 0,
                "error": (answer.error or "")[:300] if answer else "",
            }
            # 只对可疑问题加这个字段，正常问答的 detail 保持干净
            if answer and answer.injection_flags:
                detail["injection_flags"] = answer.injection_flags
            await auditor.log(
                "chat.read",
                target_type="datasource",
                target_id=ds.id,
                result="ok" if (answer and answer.ok) else "error",
                detail=detail,
            )
            await queue.put(None)

    task = asyncio.create_task(worker())

    def _consume(t: asyncio.Task) -> None:
        """worker 的异常要有人取，否则 asyncio 只会打一句 'never retrieved'。

        正常路径不会走到这里（worker 自己处理了异常），只有取消
        （进程关闭）和未捕获异常会留下痕迹。
        """
        if t.cancelled():
            logger.info("worker 被取消（服务关闭中）")
            return
        exc = t.exception()
        if exc is not None:
            logger.warning("问答任务异常：%s", exc, exc_info=exc)

    task.add_done_callback(_consume)

    async def event_source():
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            # 客户端断开时**不要取消** worker：取消会打断 finally 里的审计写入
            # （CancelledError 会在审计的 I/O 停留处再次抛出），
            # 于是「用户中途关掉页面」的请求在审计里彻底消失。
            # 让它跑完（最多一次问答的时长），结果丢弃，审计照写。
            pass

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