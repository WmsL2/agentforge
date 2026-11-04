"""Create workspace-scoped knowledge documents.

Revision ID: 0044_create_knowledge_documents
Revises: 0043_create_knowledge_bases
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0044_create_knowledge_documents"
down_revision = "0043_create_knowledge_bases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "knowledge_bases_workspace_id_id_key",
        "knowledge_bases",
        ["workspace_id", "id"],
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=127), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("parse_error_code", sa.String(length=64), nullable=True),
        sa.Column("parsed_content", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parse_metadata", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge_bases.workspace_id", "knowledge_bases.id"],
            ondelete="CASCADE",
            name="knowledge_documents_workspace_knowledge_base_fkey",
        ),
        sa.CheckConstraint(
            "parse_status IN ('ready', 'failed')",
            name="parse_status",
        ),
        sa.UniqueConstraint("storage_path", name="knowledge_documents_storage_path_key"),
    )
    op.create_index(
        "knowledge_documents_workspace_base_created_id_idx",
        "knowledge_documents",
        ["workspace_id", "knowledge_base_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "knowledge_documents_workspace_base_created_id_idx",
        table_name="knowledge_documents",
    )
    op.drop_table("knowledge_documents")
    op.drop_constraint(
        "knowledge_bases_workspace_id_id_key",
        "knowledge_bases",
        type_="unique",
    )
