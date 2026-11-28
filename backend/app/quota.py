"""每个工作空间的提问额度。

为什么是**持久计数**而不是滑动窗口：额度用完就是"这个人用完了"，重启进程不该把机会还回去。
所以计数落在 ``workspaces.questions_used``。

规则：
- ``SQLAGENT_CHAT_MAX_QUESTIONS`` 默认 5，设 0 表示不限
- **只有用平台额度才计数**：选了自建模型档（BYOK）花的是自己的钱，不该被限制
- **管理员不受限制**：站长自己要能演示、能排查问题
- 两条通道（``/chat/stream`` 与 ``/query``）共用同一个账本
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import Principal, resolve_profile
from app.models import ModelProfile, Workspace


def limit() -> int:
    return settings.chat_max_questions


def remaining(used: int) -> int | None:
    """还剩几次；``None`` 表示不限。"""
    total = limit()
    if total <= 0:
        return None
    return max(total - used, 0)


async def profile_has_key(
    session: AsyncSession, workspace_id: int, profile_id: int | None = None
) -> bool:
    """选中的那档是否带自己的 Key（带了就是 BYOK，不计额度）。"""
    profile: ModelProfile | None = await resolve_profile(session, workspace_id, profile_id)
    if profile_id is not None:
        return bool(profile and profile.api_key_enc)
    # 没指定档位：只有存在任何一档带 Key 的配置时才按 BYOK 处理
    if profile is not None and profile.api_key_enc:
        return True
    return bool(
        await session.scalar(
            select(ModelProfile.id)
            .where(
                ModelProfile.workspace_id == workspace_id,
                ModelProfile.api_key_enc.is_not(None),
            )
            .limit(1)
        )
    )


async def remaining_for(
    session: AsyncSession,
    principal: Principal,
    profile_id: int | None = None,
    *,
    byok: bool | None = None,
) -> int | None:
    """给界面看的剩余次数；``None`` = 不限。"""
    if principal.is_admin or limit() <= 0:
        return None
    if byok is None:
        byok = await profile_has_key(session, principal.workspace_id, profile_id)
    if byok:
        return None
    workspace = await session.get(Workspace, principal.workspace_id)
    if workspace is None:
        return None
    return remaining(workspace.questions_used)


async def consume(
    session: AsyncSession,
    principal: Principal,
    profile_id: int | None = None,
    *,
    byok: bool | None = None,
) -> int | None:
    """扣一次额度并返回剩余次数（``None`` = 不限）。

    余额不足时抛 429；管理员与自带 Key 的账号直接放行。
    """
    if principal.is_admin or limit() <= 0:
        return None
    if byok is None:
        byok = await profile_has_key(session, principal.workspace_id, profile_id)
    if byok:
        return None

    workspace = await session.get(Workspace, principal.workspace_id)
    if workspace is None:  # 理论上不会发生，稳妥起见按放行处理
        return None

    left = remaining(workspace.questions_used)
    if left is None or left <= 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"试用额度已用完（共 {limit()} 次提问）。"
            "想继续用，可以在「设置」里加一档自己的模型 Key，次数不限。",
        )

    workspace.questions_used += 1
    await session.commit()
    return left - 1