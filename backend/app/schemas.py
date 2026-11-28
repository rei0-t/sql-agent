"""Pydantic 出入参模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DatasourceType = Literal["mysql", "postgres", "sqlite"]
SafetyLevel = Literal["L0", "L1", "L2", "L3", "L4"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class AuthConfigOut(BaseModel):
    allow_registration: bool


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class UserAdminOut(BaseModel):
    """管理员视角的用户信息（不含口令哈希）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    is_active: bool
    workspace_id: int
    created_at: datetime


class TempPasswordOut(BaseModel):
    """重置密码时返回一次性的临时口令。"""

    password: str
    username: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    workspace_id: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class DatasourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: DatasourceType
    host: str = ""
    port: int = 0
    database: str = ""
    username: str = ""
    password: str = ""
    safety_level: SafetyLevel = "L0"
    is_prod: bool = False

    # 可写凭证必须与只读凭证分开提供（见 PLAN-v2 §3.1）
    writable_username: str | None = None
    writable_password: str | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> DatasourceCreate:
        if self.type == "sqlite":
            if not self.database:
                raise ValueError("SQLite 数据源需要填写数据库文件路径")
        else:
            missing = [
                field
                for field, value in (
                    ("host", self.host),
                    ("port", self.port),
                    ("database", self.database),
                    ("username", self.username),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"缺少必填字段: {', '.join(missing)}")

        if self.safety_level != "L0" and not (self.writable_username and self.writable_password):
            raise ValueError("安全等级高于 L0 时必须提供独立的可写账号与口令")
        return self


class DatasourceOut(BaseModel):
    id: int
    name: str
    type: str
    host: str
    port: int
    database: str
    username: str
    safety_level: str
    is_prod: bool
    has_write_credential: bool
    last_check_ok: bool | None
    last_checked_at: datetime | None
    created_at: datetime


class TestResult(BaseModel):
    ok: bool
    message: str
    server_version: str | None = None
    latency_ms: int = 0


class ColumnOut(BaseModel):
    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    comment: str | None = None


class TableOut(BaseModel):
    # 字段名叫 schema_name 是为了不遮蔽 BaseModel 上的同名方法；
    # 对外 JSON 仍然按契约输出 "schema"。
    model_config = ConfigDict(populate_by_name=True)

    name: str
    schema_name: str | None = Field(default=None, alias="schema")
    row_count_estimate: int | None = None
    columns: list[ColumnOut] = Field(default_factory=list)


class SchemaOut(BaseModel):
    datasource_id: int
    fetched_at: datetime
    tables: list[TableOut] = Field(default_factory=list)


# ---------------- 对话 ----------------


class ChatRequest(BaseModel):
    datasource_id: int
    question: str = Field(min_length=1, max_length=2000)
    # 用哪一档模型；空 = 用平台额度（试用）
    model_profile_id: int | None = None


class ChatConfigOut(BaseModel):
    # 展示用的标签（"平台额度（试用）" 或用户自己起的名字）；不含端点与真实模型名
    model_label: str = ""
    model_profile_id: int | None = None
    # 是否用平台额度（前端据此显示"试用"话术）
    using_platform: bool = True
    model: str = ""
    configured: bool
    max_rows: int
    query_timeout: int
    max_repair: int
    # 剩余提问额度；None = 不限（管理员或关闭了额度）
    remaining_questions: int | None = None
    quota_total: int | None = None


class ChatFeedbackIn(BaseModel):
    """P1 先留接口：人工纠错回灌示例库（P3 接向量/BM25 检索）。"""

    question: str = Field(min_length=1, max_length=2000)
    correct_sql: str = Field(min_length=1, max_length=8000)
    datasource_id: int
    note: str = ""


# ---------------- 模型设置（BYOK）----------------


class LlmSettingIn(BaseModel):
    base_url: str = Field(default="", max_length=255)
    model: str = Field(default="", max_length=128)
    # 不传 = 保持原值；传空串 = 清除
    api_key: str | None = Field(default=None, max_length=255)


class LlmSettingOut(BaseModel):
    base_url: str
    model: str
    api_key_masked: str | None
    configured: bool
    source: Literal["workspace", "env", "none"]
    env_model: str
    updated_at: datetime | None = None


class LlmTestIn(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class LlmTestOut(BaseModel):
    ok: bool
    message: str
    latency_ms: int = 0
    model: str | None = None


# ---------------- 开发者 API Key ----------------


class ApiKeyIn(BaseModel):
    name: str = Field(default="default", max_length=64)


class ApiKeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class ApiKeyCreatedOut(BaseModel):
    key: str
    item: ApiKeyOut


# ---------------- 开发者查询接口 ----------------


class QueryIn(BaseModel):
    datasource_id: int
    question: str = Field(min_length=1, max_length=2000)
    model_profile_id: int | None = None


class QueryOut(BaseModel):
    question: str
    sql: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)
    summary: str = ""
    explain: str = ""
    tables: list[str] = Field(default_factory=list)
    attempts: int = 0
    truncated: bool = False
    elapsed_ms: int = 0
    tokens: int = 0
    model: str = ""
    error: str | None = None
    clarification: str | None = None


# ---------------- 审计查询 ----------------


class AuditEntryOut(BaseModel):
    id: int
    created_at: datetime
    actor_name: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    result: str
    detail: dict | None = None


class AuditPageOut(BaseModel):
    items: list[AuditEntryOut]
    total: int
    limit: int
    offset: int


class AuditBucketOut(BaseModel):
    action: str
    result: str
    count: int

class ModelProfileIn(BaseModel):
    """新建/更新一档模型配置。"""

    label: str = Field(default="", max_length=64)
    base_url: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=255)


class ModelProfileOut(BaseModel):
    id: int
    label: str
    base_url: str
    model: str
    api_key_masked: str
    created_at: datetime | None = None
    last_used_at: datetime | None = None


class PlatformProfileOut(BaseModel):
    """平台额度：只说明"可用/次数上限"，不回传端点与模型名。"""

    id: int | None = None
    label: str
    kind: str = "platform"
    available: bool
    remaining: int | None = None


class ModelProfileListOut(BaseModel):
    platform: PlatformProfileOut
    items: list[ModelProfileOut]
