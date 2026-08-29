"""drop message ratings table

Revision ID: 0029_drop_message_ratings
Revises: 0028_drop_user_slash_commands
Create Date: 2026-08-29T00:00:00+00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0029_drop_message_ratings"
down_revision = "0028_drop_user_slash_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("message_ratings")


def downgrade() -> None:
    op.create_table(
        "message_ratings",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "message_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("rating IN (1, -1)", name="message_ratings_ck_rating_value_check"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_user_rating"),
    )
    op.create_index("ix_message_ratings_message_id", "message_ratings", ["message_id"])
    op.create_index("ix_message_ratings_user_id", "message_ratings", ["user_id"])
