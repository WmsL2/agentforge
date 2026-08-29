"""drop public demo support

Revision ID: 0030_drop_public_demo
Revises: 0029_drop_message_ratings
Create Date: 2026-08-29T00:00:00+00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "0030_drop_public_demo"
down_revision = "0029_drop_message_ratings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_conversations_is_demo", table_name="conversations")
    op.drop_column("conversations", "is_demo")


def downgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_conversations_is_demo", "conversations", ["is_demo"])
