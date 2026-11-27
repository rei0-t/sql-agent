"""登录、注册与会话。

注册的语义是「新开一个工作空间」：用户之间不共享数据源、模型 Key、审计记录。
所以注册不是往 users 表插一行那么简单，必须同时建 Workspace。
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Actor
from app.audit import record as audit_record
from app.config import settings
from app.deps import get_current_user, get_session
from app.models import User, Workspace
from app.schemas import (
    AuthConfigOut,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")


def _issue(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        user=UserOut.model_validate(user),
    )


@router.get("/config", response_model=AuthConfigOut)
async def auth_config() -> AuthConfigOut:
    """登录页要用：决定显不显示「注册」入口。"""
    return AuthConfigOut(allow_registration=settings.allow_registration)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        await audit_record(
            "auth.login",
            actor=Actor(workspace_id=user.workspace_id, id=user.id, name=user.username)
            if user
            else Actor.anonymous(body.username),
            result="denied",
            detail={"reason": "invalid_credentials"},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用")

    await audit_record(
        "auth.login",
        actor=Actor.of(user),
        target_type="user",
        target_id=user.id,
    )
    return _issue(user)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    if not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "当前部署未开放注册")

    username = body.username.strip()
    if not USERNAME_PATTERN.match(username):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "用户名只能用字母、数字、下划线、点、@、短横线，长度 3–64",
        )

    if await session.scalar(select(User).where(User.username == username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被占用")

    workspace = Workspace(name=f"{username} 的空间")
    session.add(workspace)
    await session.flush()

    user = User(
        username=username,
        password_hash=hash_password(body.password),
        role="owner",
        workspace_id=workspace.id,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # 并发注册同名用户时由唯一索引兜底
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被占用") from None
    await session.refresh(user)

    await audit_record(
        "auth.register",
        actor=Actor.of(user),
        target_type="user",
        target_id=user.id,
        detail={"workspace_id": workspace.id},
    )
    return _issue(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)