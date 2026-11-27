"""请求级中间件：给每个请求一个 id，写进日志与响应头。

排查线上问题时，用户截图里的 X-Request-ID 能直接对上日志和审计记录。

注意：日志里的耗时是「到响应头发出为止」。SSE 请求（/chat/stream）会显示成几十毫秒，
那是建流时间，不是整段生成时间——真正的耗时看审计里的 elapsed_ms。
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.audit import set_request_id

logger = logging.getLogger("app.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        set_request_id(request_id)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed = int((time.perf_counter() - started) * 1000)
            logger.exception("%s %s 500 %dms rid=%s", request.method, request.url.path, elapsed, request_id)
            raise

        elapsed = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        if not request.url.path.startswith(("/assets", "/favicon")):
            logger.info(
                "%s %s %d %dms rid=%s",
                request.method,
                request.url.path,
                response.status_code,
                elapsed,
                request_id,
            )
        return response