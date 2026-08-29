"""drop conversation sharing table

Revision ID: 0031_drop_conversation_sharing
Revises: 0030_drop_public_demo
Create Date: 2026-08-29T00:00:00+00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0031_drop_conversation_sharing"
down_revision = "0030_drop_public_demo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("conversation_shares")


def downgrade() -> None:
    op.create_table(
        "conversation_shares",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shared_by",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shared_with",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("share_token", sa.String(64), nullable=True, unique=True),
        sa.Column("permission", sa.String(10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("conversation_id", "shared_with", name="uq_share_conv_user"),
    )
    op.create_index(
        "ix_conversation_shares_conversation_id",
        "conversation_shares",
        ["conversation_id"],
    )
    op.create_index("ix_conversation_shares_shared_with", "conversation_shares", ["shared_with"])
