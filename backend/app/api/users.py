"""用户管理（仅管理员）。

自建场景下 admin 就是这台机器的运维：能看到所有账号、能禁用、能重置口令。
刻意不做的事：
- 不改别人的 workspace 归属（那是数据迁移，不是点一下按钮）
- 不允许禁用/降级自己（避免把自己锁在门外）
- 不允许把最后一个可用管理员降级
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Actor, Auditor
from app.deps import get_auditor, get_current_user, get_session
from app.models import User
from app.schemas import TempPasswordOut, UserAdminOut
from app.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


def _require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


async def _get_user(session: AsyncSession, user_id: int) -> User:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    return target


async def _active_admin_count(session: AsyncSession, exclude: int | None = None) -> int:
    query = select(func.count()).select_from(User).where(
        User.role == "admin", User.is_active.is_(True)
    )
    if exclude is not None:
        query = query.where(User.id != exclude)
    return int(await session.scalar(query) or 0)


@router.get("", response_model=list[UserAdminOut])
async def list_users(
    _: User = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[UserAdminOut]:
    rows = await session.scalars(select(User).order_by(User.id))
    return [UserAdminOut.model_validate(row) for row in rows]


@router.post("/{user_id}/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_user(
    user_id: int,
    admin: User = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
    auditor: Auditor = Depends(get_auditor),
) -> None:
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能禁用自己")
    target = await _get_user(session, user_id)

    if target.role == "admin" and await _active_admin_count(session, exclude=target.id) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少要保留一个可用的管理员")

    target.is_active = False
    target.token_version += 1  # 立刻踢掉在线会话
    await session.commit()

    await auditor.log(
        "user.disable",
        target_type="user",
        target_id=target.id,
        detail={"username": target.username},
    )


@router.post("/{user_id}/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_user(
    user_id: int,
    admin: User = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
    auditor: Auditor = Depends(get_auditor),
) -> None:
    target = await _get_user(session, user_id)
    target.is_active = True
    await session.commit()

    await auditor.log(
        "user.enable",
        target_type="user",
        target_id=target.id,
        detail={"username": target.username},
    )


@router.post("/{user_id}/reset-password", response_model=TempPasswordOut)
async def reset_password(
    user_id: int,
    admin: User = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
    auditor: Auditor = Depends(get_auditor),
) -> TempPasswordOut:
    """生成一次性临时口令（明文只返回这一次），并让该用户所有旧会话失效。"""
    target = await _get_user(session, user_id)

    temp = secrets.token_urlsafe(9)
    target.password_hash = hash_password(temp)
    target.token_version += 1
    await session.commit()

    await auditor.log(
        "user.reset_password",
        target_type="user",
        target_id=target.id,
        detail={"username": target.username, "by": Actor.of(admin).name},
    )
    return TempPasswordOut(password=temp, username=target.username)