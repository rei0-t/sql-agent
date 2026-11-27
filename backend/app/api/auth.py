"""登录、注册与会话。

注册的语义是「新开一个工作空间」：用户之间不共享数据源、模型 Key、审计记录。
所以注册不是往 users 表插一行那么简单，必须同时建 Workspace。

登录带**失败限流**（同一 IP、同一用户名各一个滑动窗口）。
注意这是**硬锁定**：超限后连正确密码也拒绝，直到窗口过期——

- 为什么必须这样：一旦允许「正确密码穿过限流」，攻击者就能以全速继续猜
  （每次得到 429 或 200，等于没有限速）。
- 代价：知道用户名的人可以把你锁住最多 `SQLAGENT_LOGIN_FAILURE_WINDOW` 秒。
  单机自建场景可接受；公网多租户建议把窗口调短，或在反代层再加一道。
- 解除：等待窗口过期、重启进程，或调用 `reset_login_limits()`。
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import csrf
from app.audit import Actor
from app.audit import record as audit_record
from app.config import settings
from app.deps import get_current_user, get_session, verify_csrf
from app.models import User, Workspace
from app.ratelimit import SlidingWindowLimiter
from app.schemas import (
    AuthConfigOut,
    LoginRequest,
    PasswordChangeIn,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")

# 进程内限流器：单进程部署够用；多副本时由反代/WAF 兜底（见 deploy 文档）
_login_limiter = SlidingWindowLimiter(
    limit=settings.login_max_failures_per_ip,
    window_seconds=settings.login_failure_window,
)
_user_limiter = SlidingWindowLimiter(
    limit=settings.login_max_failures_per_user,
    window_seconds=settings.login_failure_window,
)
# 注册按"成功建号"计数：只是重名/格式错不该占用额度
_register_limiter = SlidingWindowLimiter(
    limit=settings.register_max_per_ip,
    window_seconds=settings.register_window,
)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def reset_limits() -> None:
    """测试与运维用：清空所有限流计数。"""
    _login_limiter.clear()
    _user_limiter.clear()
    _register_limiter.clear()


def _issue(response: Response, user: User) -> TokenResponse:
    """签发令牌并写会话 cookie。

    浏览器走 httpOnly cookie（JS 读不到，XSS 偷不走）；
    脚本/CI 仍可直接用响应体里的 token 走 Authorization 头。
    """
    token = create_access_token(str(user.id), user.token_version)
    options = {
        "max_age": settings.access_token_ttl_minutes * 60,
        "path": "/",
        "samesite": "lax",
        "secure": settings.cookie_secure,
    }
    response.set_cookie(csrf.SESSION_COOKIE, token, httponly=True, **options)
    # CSRF cookie 必须能被 JS 读到，否则前端没法把它放进请求头
    response.set_cookie(csrf.CSRF_COOKIE, csrf.new_token(), httponly=False, **options)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/config", response_model=AuthConfigOut)
async def auth_config() -> AuthConfigOut:
    """登录页要用：决定显不显示「注册」入口。"""
    return AuthConfigOut(allow_registration=settings.allow_registration)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    ip_key = f"ip:{_client_ip(request)}"
    user_key = f"user:{body.username.lower()}"

    if settings.login_ratelimit_enabled:
        for decision in (_login_limiter.check(ip_key), _user_limiter.check(user_key)):
            if not decision.allowed:
                await audit_record(
                    "auth.login",
                    actor=Actor.anonymous(body.username),
                    result="denied",
                    detail={"reason": "rate_limited", "retry_after": decision.retry_after},
                )
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"失败次数过多，请 {decision.retry_after} 秒后再试",
                    headers={"Retry-After": str(decision.retry_after)},
                )

    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        if settings.login_ratelimit_enabled:
            _login_limiter.hit(ip_key)
            _user_limiter.hit(user_key)
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

    # 登录成功就清掉失败计数；这只在「还没超限」时有意义——
    # 一旦硬锁定生效，正确密码也进不来（见模块 docstring 的取舍说明）
    if settings.login_ratelimit_enabled:
        _login_limiter.reset(ip_key)
        _user_limiter.reset(user_key)

    await audit_record(
        "auth.login",
        actor=Actor.of(user),
        target_type="user",
        target_id=user.id,
    )
    return _issue(response, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, _: None = Depends(verify_csrf)) -> None:
    """清掉会话与 CSRF cookie。

    这里不要求登录（没登录也能安全地"退出"），但**要校验 CSRF**：
    否则第三方页面 POST 一下就能把用户踢下线。
    """

    response.delete_cookie(csrf.SESSION_COOKIE, path="/")
    response.delete_cookie(csrf.CSRF_COOKIE, path="/")


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeIn,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """改密码：校验旧密码 → 换哈希 → 自增 token_version（旧令牌全部失效）→ 续签当前会话。"""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前密码不正确")
    if body.current_password == body.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新密码不能与当前密码相同")

    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    await session.commit()

    await audit_record(
        "auth.password_change",
        actor=Actor.of(user),
        target_type="user",
        target_id=user.id,
    )
    # 其它设备上的旧令牌已失效；当前这个再签一张，避免改完密码自己被踢下线
    _issue(response, user)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    if not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "当前部署未开放注册")

    ip_key = f"ip:{_client_ip(request)}"
    if settings.register_ratelimit_enabled:
        decision = _register_limiter.check(ip_key)
        if not decision.allowed:
            await audit_record(
                "auth.register",
                actor=Actor.anonymous(body.username),
                result="denied",
                detail={"reason": "rate_limited", "retry_after": decision.retry_after},
            )
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"注册过于频繁，请 {decision.retry_after} 秒后再试",
                headers={"Retry-After": str(decision.retry_after)},
            )

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

    if settings.register_ratelimit_enabled:
        _register_limiter.hit(ip_key)

    await audit_record(
        "auth.register",
        actor=Actor.of(user),
        target_type="user",
        target_id=user.id,
        detail={"workspace_id": workspace.id},
    )
    return _issue(response, user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)