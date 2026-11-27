"""会话 cookie 与 CSRF 防护。

为什么要有这一层：登录态从 localStorage 挪到 httpOnly cookie 之后，浏览器会自动
带上 cookie，于是任何第三方页面发起的表单 POST 都会"自带凭证"——这就是 CSRF。

采用双提交（double submit）：登录时同时下发两个 cookie
- ``sa_session``：httpOnly，真正的令牌，JS 读不到
- ``sa_csrf``：非 httpOnly，前端读出来放进 ``X-CSRF-Token`` 头

服务端只对**用 cookie 认证的**写操作校验两者的常量时间相等；
用 Authorization 头的调用（API Key / curl）不受影响。
"""

from __future__ import annotations

import hmac
import secrets

CSRF_COOKIE = "sa_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_COOKIE = "sa_session"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def new_token() -> str:
    return secrets.token_urlsafe(32)


def matches(header_value: str | None, cookie_value: str | None) -> bool:
    if not header_value or not cookie_value:
        return False
    return hmac.compare_digest(header_value, cookie_value)