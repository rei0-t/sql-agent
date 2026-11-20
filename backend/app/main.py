"""SQL-agent 后端入口。

- 开发期：``uvicorn app.main:app --reload``，前端跑 Vite dev server（5173）并代理 /api 到这里。
- 生产期：如果把前端构建产物放在 ``frontend/dist``，这里会直接把它当静态站点托管，
  单进程即可对外服务（见 deploy/Dockerfile）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import auth, chat, datasources, health, keys, query
from app.api import settings as settings_api
from app.config import settings
from app.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(datasources.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(settings_api.router, prefix="/api/v1")
app.include_router(keys.router, prefix="/api/v1")
app.include_router(query.router, prefix="/api/v1")


@app.api_route(
    "/api/{rest:path}",
    methods=["POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def api_not_found(rest: str) -> None:
    """未实现的 API 一律 404。

    变更通道（/api/v1/mutation/*）本期不实现，这里保证调用方拿到的是
    「不存在」而不是被 SPA 兜底路由误判成 405。
    """
    raise HTTPException(404, f"/api/{rest} 不存在")


def _mount_frontend() -> bool:
    dist = settings.frontend_dist
    index = dist / "index.html"
    if not index.exists():
        return False

    assets = dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)

    return True


if not _mount_frontend():

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "app": settings.app_name,
                "version": __version__,
                "docs": "/docs",
                "health": "/api/v1/health",
                "hint": "前端产物未构建。开发时请启动 frontend 的 Vite dev server（5173）。",
            }
        )