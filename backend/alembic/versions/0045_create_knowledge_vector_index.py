"""Create durable knowledge indexing jobs and pgvector chunks.

Revision ID: 0045_create_knowledge_vector_index
Revises: 0044_create_knowledge_documents
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0045_create_knowledge_vector_index"
down_revision = "0044_create_knowledge_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "knowledge_documents",
        sa.Column("active_index_generation_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        "knowledge_documents_workspace_base_id_key",
        "knowledge_documents",
        ["workspace_id", "knowledge_base_id", "id"],
    )
    op.create_table(
        "knowledge_index_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("index_generation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("chunking_config_version", sa.String(length=128), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claim_token", UUID(as_uuid=True), nullable=True),
        sa.Column("claim_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            ondelete="CASCADE",
            name="knowledge_index_jobs_document_owner_fkey",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        sa.CheckConstraint("claim_generation >= 0", name="claim_generation_nonnegative"),
        sa.CheckConstraint("embedding_dimensions = 1536", name="embedding_dimensions_1536"),
        sa.CheckConstraint(
            "(status = 'running' AND claim_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'running' AND claim_token IS NULL AND lease_expires_at IS NULL)",
            name="claim_state_consistent",
        ),
        sa.CheckConstraint(
            "chunk_count IS NULL OR chunk_count >= 0", name="chunk_count_nonnegative"
        ),
        sa.UniqueConstraint(
            "index_generation_id", name="knowledge_index_jobs_generation_key"
        ),
    )
    op.create_index(
        "knowledge_index_jobs_owner_document_created_idx",
        "knowledge_index_jobs",
        ["workspace_id", "knowledge_base_id", "document_id", "created_at"],
    )
    op.create_index(
        "knowledge_index_jobs_one_active_per_document_idx",
        "knowledge_index_jobs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_table(
        "knowledge_document_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("index_generation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("chunk_metadata", JSONB(), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            ondelete="CASCADE",
            name="knowledge_document_chunks_document_owner_fkey",
        ),
        sa.CheckConstraint("chunk_index >= 0", name="chunk_index_nonnegative"),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset", name="valid_offsets"
        ),
        sa.CheckConstraint(
            "(page_start IS NULL AND page_end IS NULL) OR "
            "(page_start >= 1 AND page_end >= page_start)",
            name="valid_pages",
        ),
        sa.UniqueConstraint(
            "document_id",
            "index_generation_id",
            "chunk_index",
            name="knowledge_document_chunks_generation_index_key",
        ),
    )
    op.create_index(
        "knowledge_document_chunks_owner_generation_idx",
        "knowledge_document_chunks",
        ["workspace_id", "knowledge_base_id", "document_id", "index_generation_id"],
    )
    op.create_index(
        "knowledge_document_chunks_embedding_hnsw_idx",
        "knowledge_document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "knowledge_document_chunks_embedding_hnsw_idx",
        table_name="knowledge_document_chunks",
        postgresql_using="hnsw",
    )
    op.drop_index(
        "knowledge_document_chunks_owner_generation_idx",
        table_name="knowledge_document_chunks",
    )
    op.drop_table("knowledge_document_chunks")
    op.drop_index(
        "knowledge_index_jobs_one_active_per_document_idx",
        table_name="knowledge_index_jobs",
    )
    op.drop_index(
        "knowledge_index_jobs_owner_document_created_idx",
        table_name="knowledge_index_jobs",
    )
    op.drop_table("knowledge_index_jobs")
    op.drop_constraint(
        "knowledge_documents_workspace_base_id_key",
        "knowledge_documents",
        type_="unique",
    )
    op.drop_column("knowledge_documents", "active_index_generation_id")
    # The vector extension may be shared by other applications in the database.
    # Deliberately retain it on downgrade.
