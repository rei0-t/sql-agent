"""给 workspaces 加 questions_used：每人固定的提问额度。

revision: 0003_workspace_questions
down_revision: 0002_user_token_version
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_workspace_questions"
down_revision = "0002_user_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(
            sa.Column("questions_used", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("questions_used")