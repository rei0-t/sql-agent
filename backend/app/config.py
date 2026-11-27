"""全局配置。

所有配置项均可通过 ``SQLAGENT_`` 前缀的环境变量覆盖，例如 ``SQLAGENT_PORT=9000``。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（本文件位于 backend/app/config.py）
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SQLAGENT_",
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SQL-agent"
    version: str = "0.1.0"
    debug: bool = False

    # 服务
    host: str = "127.0.0.1"
    port: int = 8080
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    # 元数据库（会话/数据源/审计）。生产建议 PostgreSQL。
    database_url: str | None = None
    data_dir: Path = BASE_DIR / "data"

    # 安全
    secret_key: str = "dev-only-change-me-before-any-real-use"
    access_token_ttl_minutes: int = 720

    # 首次启动时创建的管理员
    admin_username: str = "admin"
    admin_password: str = "sqlagent123"

    # 是否允许自助注册（每个新用户自动获得独立工作空间）
    allow_registration: bool = True

    # 数据源连接池/超时（秒）
    connect_timeout: int = 5
    query_timeout: int = 10

    # ---- 模型（OpenAI 兼容端点）----
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    llm_api_key: str = ""
    llm_timeout: int = 60
    llm_temperature: float = 0.0
    # 固定采样种子，便于复现与评测；留空则不下发该参数
    llm_seed: int | None = None

    # ---- 只读通道限额 ----
    read_max_rows: int = 200
    max_repair: int = 3
    schema_max_tables: int = 8
    schema_sample_rows: int = 3
    schema_cache_ttl: int = 60
    # 缓存条目上限：防止数据源很多时内存一直涨
    schema_cache_max_entries: int = 64
    # 是否取精确行数：SQLite 的 COUNT(*) 是全表扫描，大表上会拖慢首次请求
    schema_row_counts: bool = True
    # 取行数的总预算（秒）：超时就放弃，只影响「约 N 行」这个提示
    schema_row_counts_budget: float = 2.0

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{(self.data_dir / 'sqlagent.db').as_posix()}"

    @property
    def frontend_dist(self) -> Path:
        return REPO_ROOT / "frontend" / "dist"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()