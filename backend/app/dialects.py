"""数据库方言适配层。

v0.1 只支持 MySQL / PostgreSQL / SQLite。所有方言差异都收敛在这里：
DSN 构造、连接参数、版本查询、行数估算。新增数据库 = 新增一个子类。
"""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import settings
from app.models import Datasource
from app.schemas import TestResult


class UnsupportedDialect(ValueError):
    pass


def _short_error(exc: Exception) -> str:
    """把驱动的长错误压成一行，方便直接展示给用户。"""
    message = " ".join(str(exc).strip().split())
    if len(message) > 300:
        message = message[:300] + "…"
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


class Dialect:
    """方言基类。子类只需覆写类属性与四个方法。"""

    name: str = ""
    driver: str = ""
    default_port: int = 0

    # ---- 连接 ----
    def dsn(self, ds: Datasource, password: str, *, writable: bool = False) -> str:
        raise NotImplementedError

    def create_engine(
        self, ds: Datasource, password: str, *, writable: bool = False
    ) -> AsyncEngine:
        raise NotImplementedError

    # ---- 元信息 ----
    async def server_version(self, conn: AsyncConnection) -> str:
        raise NotImplementedError

    async def row_counts(self, conn: AsyncConnection, tables: list[str]) -> dict[str, int]:
        return {}


class SQLiteDialect(Dialect):
    name = "sqlite"
    driver = "aiosqlite"
    default_port = 0

    @staticmethod
    def resolve_path(database: str) -> Path:
        path = Path(database)
        return path if path.is_absolute() else settings.data_dir / path

    def dsn(self, ds: Datasource, password: str, *, writable: bool = False) -> str:
        # 只读通道用 SQLite 的 URI 只读模式：即使上层代码写错，也写不进去。
        path = self.resolve_path(ds.database).as_posix()
        mode = "rw" if writable else "ro"
        return f"sqlite+aiosqlite:///file:{path}?uri=true&mode={mode}"

    def create_engine(self, ds, password, *, writable: bool = False) -> AsyncEngine:
        return create_async_engine(
            self.dsn(ds, password, writable=writable),
            connect_args={"timeout": settings.connect_timeout},
        )

    async def server_version(self, conn: AsyncConnection) -> str:
        return f"SQLite {await conn.scalar(text('select sqlite_version()'))}"

    async def row_counts(self, conn: AsyncConnection, tables: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        # SQLite 没有统计信息表，只能真数；限制表数量防止页面卡死。
        for name in tables[:50]:
            try:
                counts[name.lower()] = int(await conn.scalar(text(f'SELECT COUNT(*) FROM "{name}"')))
            except Exception:  # noqa: BLE001 - 单表失败不影响整体
                continue
        return counts


class MySQLDialect(Dialect):
    name = "mysql"
    driver = "aiomysql"
    default_port = 3306

    def dsn(self, ds: Datasource, password: str, *, writable: bool = False) -> str:
        user = ds.writable_username if writable and ds.writable_username else ds.username
        return (
            f"mysql+aiomysql://{quote_plus(user)}:{quote_plus(password)}"
            f"@{ds.host}:{ds.port}/{quote_plus(ds.database)}?charset=utf8mb4"
        )

    def create_engine(self, ds, password, *, writable: bool = False) -> AsyncEngine:
        return create_async_engine(
            self.dsn(ds, password, writable=writable),
            pool_pre_ping=True,
            connect_args={"connect_timeout": settings.connect_timeout},
        )

    async def server_version(self, conn: AsyncConnection) -> str:
        return f"MySQL {await conn.scalar(text('select version()'))}"

    async def row_counts(self, conn: AsyncConnection, tables: list[str]) -> dict[str, int]:
        rows = await conn.execute(
            text(
                "SELECT table_name, table_rows FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            )
        )
        return {str(name).lower(): int(count or 0) for name, count in rows.all()}


class PostgresDialect(Dialect):
    name = "postgres"
    driver = "asyncpg"
    default_port = 5432

    def dsn(self, ds: Datasource, password: str, *, writable: bool = False) -> str:
        user = ds.writable_username if writable and ds.writable_username else ds.username
        return (
            f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(password)}"
            f"@{ds.host}:{ds.port}/{quote_plus(ds.database)}"
        )

    def create_engine(self, ds, password, *, writable: bool = False) -> AsyncEngine:
        return create_async_engine(
            self.dsn(ds, password, writable=writable),
            pool_pre_ping=True,
            connect_args={"timeout": settings.connect_timeout},
        )

    async def server_version(self, conn: AsyncConnection) -> str:
        return str(await conn.scalar(text("select version()")))

    async def row_counts(self, conn: AsyncConnection, tables: list[str]) -> dict[str, int]:
        rows = await conn.execute(
            text(
                "SELECT c.relname, c.reltuples::bigint FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind = 'r' AND n.nspname = ANY (current_schemas(false))"
            )
        )
        return {str(name).lower(): int(count or 0) for name, count in rows.all()}


_DIALECTS: dict[str, Dialect] = {
    "sqlite": SQLiteDialect(),
    "mysql": MySQLDialect(),
    "postgres": PostgresDialect(),
}


def get_dialect(name: str) -> Dialect:
    try:
        return _DIALECTS[name]
    except KeyError as exc:
        raise UnsupportedDialect(f"暂不支持的数据源类型: {name}") from exc


async def test_connection(ds: Datasource, password: str) -> TestResult:
    """连通性探测：只做一次握手 + 版本查询。"""
    dialect = get_dialect(ds.type)
    started = time.perf_counter()
    engine: AsyncEngine | None = None
    try:
        engine = dialect.create_engine(ds, password)
        async with engine.connect() as conn:
            version = await dialect.server_version(conn)
        return TestResult(
            ok=True,
            message="连接成功",
            server_version=version,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 - 驱动异常类型极多，统一转成可读信息
        return TestResult(
            ok=False,
            message=_short_error(exc),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    finally:
        if engine is not None:
            await engine.dispose()