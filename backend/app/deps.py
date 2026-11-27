"""FastAPI 依赖：会话、当前用户、模型客户端、API Key 身份。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apikeys import hash_api_key, looks_like_api_key
from app.audit import Actor, Auditor
from app.config import settings
from app.db import SessionLocal
from app.engine.llm import ChatModel, OpenAICompatibleModel, get_default_model
from app.models import ApiKey, LlmSetting, User, utcnow
from app.security import decode_access_token, get_secret_box

bearer_scheme = HTTPBearer(auto_error=False)

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="未登录或凭证无效",
    headers={"WWW-Authenticate": "Bearer"},
)


@dataclass
class Principal:
    """调用者身份：登录用户或开发者 API Key。"""

    workspace_id: int
    actor_id: int | None
    actor_name: str
    via: Literal["session", "api_key"]

    # 兼容 User 的字段名，方便路由里同一套代码同时服务两种身份
    @property
    def id(self) -> int | None:
        return self.actor_id

    @property
    def username(self) -> str:
        return self.actor_name


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise UNAUTHORIZED
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise UNAUTHORIZED
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise UNAUTHORIZED from None

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise UNAUTHORIZED
    return user


async def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    """同时接受登录令牌与开发者 API Key。"""
    if credentials is None:
        raise UNAUTHORIZED

    token = credentials.credentials
    if looks_like_api_key(token):
        record = await session.scalar(
            select(ApiKey).where(ApiKey.key_hash == hash_api_key(token))
        )
        if record is None or record.revoked_at is not None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "API Key 无效或已吊销",
                headers={"WWW-Authenticate": "Bearer"},
            )
        record.last_used_at = utcnow()
        await session.commit()
        return Principal(
            workspace_id=record.workspace_id,
            actor_id=None,
            actor_name=f"api-key:{record.name or record.prefix}",
            via="api_key",
        )

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise UNAUTHORIZED
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise UNAUTHORIZED from None

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise UNAUTHORIZED
    return Principal(
        workspace_id=user.workspace_id,
        actor_id=user.id,
        actor_name=user.username,
        via="session",
    )


async def get_auditor(principal: Principal = Depends(get_principal)) -> Auditor:
    """绑定当前调用者的审计写入器（JWT 与 API Key 都适用）。"""
    return Auditor(actor=Actor.of(principal))


async def build_model(session: AsyncSession, workspace_id: int) -> ChatModel:
    """按工作空间解析模型：界面里配了就用界面的，没配回退到环境变量。"""
    setting = await session.scalar(
        select(LlmSetting).where(LlmSetting.workspace_id == workspace_id)
    )
    if setting and setting.api_key_enc:
        return OpenAICompatibleModel(
            base_url=setting.base_url or settings.llm_base_url,
            api_key=get_secret_box().decrypt(setting.api_key_enc),
            model=setting.model or settings.llm_model,
            timeout=settings.llm_timeout,
            temperature=settings.llm_temperature,
            seed=settings.llm_seed,
        )
    return get_default_model()


async def get_model(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatModel:
    """取模型客户端。

    测试里把 `app.state.llm` 换成 FakeModel 即可，不需要打补丁或 monkeypatch。
    """
    override = getattr(request.app.state, "llm", None)
    if override is not None:
        return override
    return await build_model(session, user.workspace_id)


async def get_model_for_principal(
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> ChatModel:
    """开发者接口用：按 API Key 所属工作空间解析模型。"""
    override = getattr(request.app.state, "llm", None)
    if override is not None:
        return override
    return await build_model(session, principal.workspace_id)