"""每个工作空间的提问额度。

为什么是**持久计数**而不是滑动窗口：额度用完就是"这个人用完了"，重启进程不该把机会还回去。
所以计数落在 ``workspaces.questions_used``。

规则：
- ``SQLAGENT_CHAT_MAX_QUESTIONS`` 默认 5，设 0 表示不限
- **只有用站点公共 Key 才计额度**：自己配了 Key（BYOK）的人花的是自己的钱，不该被限制
- **管理员不受限制**：站长自己要能演示、能排查问题
- 两条通道（``/chat/stream`` 与 ``/query``）共用同一个账本
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import Principal
from app.models import LlmSetting, Workspace


def limit() -> int:
    return settings.chat_max_questions


def remaining(used: int) -> int | None:
    """还剩几次；``None`` 表示不限。"""
    total = limit()
    if total <= 0:
        return None
    return max(total - used, 0)


async def uses_own_key(session: AsyncSession, workspace_id: int) -> bool:
    """这个工作空间是否配了自己的模型 Key（配了就按 BYOK 处理，不计额度）。"""
    row = await session.scalar(
        select(LlmSetting).where(LlmSetting.workspace_id == workspace_id)
    )
    return bool(row and row.api_key_enc)


async def remaining_for(session: AsyncSession, principal: Principal) -> int | None:
    """给界面看的剩余次数；``None`` = 不限。"""
    if principal.is_admin or limit() <= 0:
        return None
    if await uses_own_key(session, principal.workspace_id):
        return None
    workspace = await session.get(Workspace, principal.workspace_id)
    if workspace is None:
        return None
    return remaining(workspace.questions_used)


async def consume(session: AsyncSession, principal: Principal) -> int | None:
    """扣一次额度并返回剩余次数（``None`` = 不限）。

    余额不足时抛 429；管理员与自带 Key 的账号直接放行。
    """
    if principal.is_admin or limit() <= 0:
        return None
    if await uses_own_key(session, principal.workspace_id):
        return None

    workspace = await session.get(Workspace, principal.workspace_id)
    if workspace is None:  # 理论上不会发生，稳妥起见按放行处理
        return None

    left = remaining(workspace.questions_used)
    if left is None or left <= 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"试用额度已用完（共 {limit()} 次提问）。"
            "想继续用，可以在「设置」里填自己的模型 Key，次数不限。",
        )

    workspace.questions_used += 1
    await session.commit()
    return left - 1