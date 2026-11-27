"""审计层：所有敏感动作写一条只追加记录。

三条设计约定：

1. **独立事务**。审计用自建的 session 单独提交，不掺和业务事务——业务回滚了，
   审计也要留下痕迹（登录失败就是典型场景）。
2. **失败不抛**。审计写失败只记日志，绝不让请求失败。
3. **带请求 id**。每条记录自动带上 X-Request-ID，便于把「前端报错截图」和「后端日志」对上。

调用方式（路由里）：

    auditor: Auditor = Depends(get_auditor)
    await auditor.log("datasource.create", target_type="datasource", target_id=ds.id, detail={...})
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.db import SessionLocal
from app.models import AuditLog

logger = logging.getLogger(__name__)

_request_id: ContextVar[str] = ContextVar("request_id", default="")


def set_request_id(value: str) -> None:
    _request_id.set(value)


def current_request_id() -> str:
    return _request_id.get()


@dataclass(slots=True)
class Actor:
    """谁做的这件事。未登录场景（登录失败、注册前）用 anonymous。"""

    workspace_id: int
    id: int | None = None
    name: str = ""

    @classmethod
    def of(cls, who: Any) -> Actor:
        """从 User 或 Principal 构造：两者都有 workspace_id / id / username。"""
        return cls(
            workspace_id=int(getattr(who, "workspace_id", 0) or 0),
            id=getattr(who, "id", None),
            name=str(getattr(who, "username", "") or ""),
        )

    @classmethod
    def anonymous(cls, name: str = "") -> Actor:
        return cls(workspace_id=0, id=None, name=name)


@dataclass(slots=True)
class Auditor:
    """绑定当前调用者的审计写入器，由依赖注入提供。"""

    actor: Actor
    request_id: str = field(default_factory=current_request_id)

    async def log(
        self,
        action: str,
        *,
        target_type: str | None = None,
        target_id: str | int | None = None,
        result: str = "ok",
        detail: dict[str, Any] | None = None,
    ) -> None:
        await record(
            action,
            actor=self.actor,
            target_type=target_type,
            target_id=target_id,
            result=result,
            detail=detail,
            request_id=self.request_id,
        )


async def record(
    action: str,
    *,
    actor: Actor,
    target_type: str | None = None,
    target_id: str | int | None = None,
    result: str = "ok",
    detail: dict[str, Any] | None = None,
    request_id: str = "",
) -> None:
    payload = dict(detail or {})
    rid = request_id or current_request_id()
    if rid:
        payload.setdefault("request_id", rid)

    try:
        async with SessionLocal() as session:
            session.add(
                AuditLog(
                    workspace_id=actor.workspace_id,
                    actor_id=actor.id,
                    actor_name=actor.name,
                    action=action,
                    target_type=target_type,
                    target_id=None if target_id is None else str(target_id),
                    result=result,
                    detail=json.dumps(payload, ensure_ascii=False, default=str) if payload else None,
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - 审计失败不能拖垮请求
        logger.warning("审计写入失败 action=%s", action, exc_info=True)