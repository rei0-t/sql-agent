"""新增 model_profiles：一个工作空间可以有多档模型配置。

同时把旧的单档 ``llm_settings``（有 Key 的那些）搬进来，标成「默认模型」，
这样升级后用户在对话页仍能直接选到它。

revision: 0004_model_profiles
down_revision: 0003_workspace_questions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_model_profiles"
down_revision = "0003_workspace_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("label", sa.String(64), nullable=False, server_default="我的模型"),
        sa.Column("base_url", sa.String(255), nullable=False, server_default=""),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("api_key_enc", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_model_profiles_workspace_id", "model_profiles", ["workspace_id"])

    # 旧单档配置搬进新表（只搬有 Key 的，否则没有意义）
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO model_profiles (workspace_id, label, base_url, model, api_key_enc, created_at)
            SELECT workspace_id, '默认模型', COALESCE(base_url, ''), COALESCE(model, ''),
                   api_key_enc, updated_at
            FROM llm_settings
            WHERE api_key_enc IS NOT NULL AND api_key_enc <> ''
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_model_profiles_workspace_id", table_name="model_profiles")
    op.drop_table("model_profiles")