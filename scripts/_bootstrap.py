"""脚本的公共引导：把 backend/ 放进 sys.path。

为什么要单独一个文件：这些脚本会被放在两种布局里运行——
- 仓库里：``scripts/`` 与 ``backend/`` 平级
- 容器里：脚本在 ``/app/scripts``，后端在 ``/app/backend``（镜像里 WORKDIR 是 /app/backend）

早期版本写死了 ``parent.parent / "backend"``，在容器布局下会算成 ``/app/backend/backend``，
于是 ``from app.config import ...`` 直接 ImportError。这里按"能不能找到 app 包"来判断。
"""

from __future__ import annotations

import sys
from pathlib import Path


def backend_dir() -> Path:
    here = Path(__file__).resolve().parent
    candidates = (here.parent / "backend", here.parent)
    # 优先选既有 app/ 又有 alembic.ini 的（容器与仓库都满足）
    for candidate in candidates:
        if (candidate / "app").is_dir() and (candidate / "alembic.ini").exists():
            return candidate
    for candidate in candidates:
        if (candidate / "app").is_dir():
            return candidate
    return here.parent / "backend"


def ensure_backend() -> Path:
    """把 backend/ 与 backend/migrations 加进 sys.path，返回 backend 目录。"""
    backend = backend_dir()
    for path in (backend, backend / "migrations"):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return backend