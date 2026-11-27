"""每个工作空间的提问额度。

为什么是**持久计数**而不是滑动窗口：额度用完就是"这个人用完了"，重启进程不该把机会还回去。
所以计数落在 ``workspaces.questions_used``，窗口限流只用来挡短时间的暴力刷取（不存在了）。

规则：
- ``SQLAGENT_CHAT_MAX_QUESTIONS`` 默认 5，设 0 表示不限
- **管理员不受限制**：站长自己要能演示、要能排查问题，不能被自己设的额度挡住
- 两条通道（``/chat/stream`` 与 ``/query``）共用同一个账本
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import Principal
from app.models import Workspace


def limit() -> int:
    return settings.chat_max_questions


def remaining(used: int) -> int | None:
    """还剩几次；``None`` 表示不限。"""
    total = limit()
    if total <= 0:
        return None
    return max(total - used, 0)


async def consume(session: AsyncSession, principal: Principal) -> int | None:
    """扣一次额度并返回剩余次数（``None`` = 不限）。

    余额不足时抛 429；管理员直接放行。
    """
    if principal.is_admin:
        return None

    total = limit()
    if total <= 0:
        return None

    workspace = await session.get(Workspace, principal.workspace_id)
    if workspace is None:  # 理论上不会发生，稳妥起见按放行处理
        return None

    left = remaining(workspace.questions_used)
    if left is None or left <= 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"试用额度已用完（共 {total} 次提问）。想要更多，请联系站点管理员。",
        )

    workspace.questions_used += 1
    await session.commit()
    return left - 1