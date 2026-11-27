"""按工作空间的问答配额。

为什么需要它：一旦部署方在 ``.env.prod`` 里放了一个公共模型 Key，所有访客都会花同一份额度。
注册限流挡的是"造号"，这里挡的是"刷问答"——一个号也能把额度烧光。

为什么按工作空间而不是按 IP：一个工作空间大致等于一个人，IP 会变（手机/公司/WiFi），
而工作空间不会。

计数按"问题"算，不按 SSE 事件算：一次问答只消耗一格。

限流器**懒创建**：上限配在 ``settings`` 里，改配置（或测试里 monkeypatch）后
下一次检查就会用新值重建计数窗口。代价是调大上限时计数会清零，这是刻意接受的。
"""

from __future__ import annotations

from app.config import settings
from app.ratelimit import Decision, SlidingWindowLimiter

_limiter: SlidingWindowLimiter | None = None
_limiter_limit: int | None = None


def _current() -> SlidingWindowLimiter:
    global _limiter, _limiter_limit
    limit = settings.chat_max_per_hour
    if _limiter is None or _limiter_limit != limit:
        _limiter = SlidingWindowLimiter(limit=limit, window_seconds=3600, max_keys=4096)
        _limiter_limit = limit
    return _limiter


def _key(workspace_id: int) -> str:
    return f"ws:{workspace_id}"


def check_chat(workspace_id: int) -> Decision | None:
    """超限返回决策（含 retry_after），放行返回 None。"""
    if not settings.chat_ratelimit_enabled:
        return None
    decision = _current().check(_key(workspace_id))
    return None if decision.allowed else decision


def hit_chat(workspace_id: int) -> None:
    if settings.chat_ratelimit_enabled:
        _current().hit(_key(workspace_id))


def reset_chat_limits() -> None:
    """测试与运维用。"""
    _current().clear()