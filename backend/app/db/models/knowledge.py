"""Workspace-scoped knowledge base persistence model."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class KnowledgeBase(Base, TimestampMixin):
    """A durable knowledge base owned by exactly one workspace."""

    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "name",
            name="knowledge_bases_workspace_id_name_key",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="knowledge_bases_workspace_id_id_key",
        ),
        Index(
            "knowledge_bases_workspace_created_id_idx",
            "workspace_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class KnowledgeDocument(Base, TimestampMixin):
    """A privately stored, parsed document owned by one knowledge base."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge_bases.workspace_id", "knowledge_bases.id"],
            ondelete="CASCADE",
            name="knowledge_documents_workspace_knowledge_base_fkey",
        ),
        CheckConstraint(
            "parse_status IN ('ready', 'failed')",
            name="parse_status",
        ),
        UniqueConstraint("storage_path", name="knowledge_documents_storage_path_key"),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="knowledge_documents_workspace_base_id_key",
        ),
        Index(
            "knowledge_documents_workspace_base_created_id_idx",
            "workspace_id",
            "knowledge_base_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False)
    parse_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parsed_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(nullable=True)
    parse_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    active_index_generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class KnowledgeDocumentChunk(Base):
    """One source-grounded vector in a document index generation."""

    __tablename__ = "knowledge_document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            ondelete="CASCADE",
            name="knowledge_document_chunks_document_owner_fkey",
        ),
        UniqueConstraint(
            "document_id",
            "index_generation_id",
            "chunk_index",
            name="knowledge_document_chunks_generation_index_key",
        ),
        CheckConstraint("chunk_index >= 0", name="chunk_index_nonnegative"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="valid_offsets"),
        CheckConstraint(
            "(page_start IS NULL AND page_end IS NULL) OR "
            "(page_start >= 1 AND page_end >= page_start)",
            name="valid_pages",
        ),
        Index(
            "knowledge_document_chunks_owner_generation_idx",
            "workspace_id",
            "knowledge_base_id",
            "document_id",
            "index_generation_id",
        ),
        Index(
            "knowledge_document_chunks_embedding_hnsw_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    index_generation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class KnowledgeIndexJob(Base, TimestampMixin):
    """Durable, lease-owned construction of one document index generation."""

    __tablename__ = "knowledge_index_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            ondelete="CASCADE",
            name="knowledge_index_jobs_document_owner_fkey",
        ),
        CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed')", name="status"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("claim_generation >= 0", name="claim_generation_nonnegative"),
        CheckConstraint("embedding_dimensions = 1536", name="embedding_dimensions_1536"),
        CheckConstraint(
            "(status = 'running' AND claim_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'running' AND claim_token IS NULL AND lease_expires_at IS NULL)",
            name="claim_state_consistent",
        ),
        CheckConstraint("chunk_count IS NULL OR chunk_count >= 0", name="chunk_count_nonnegative"),
        UniqueConstraint("index_generation_id", name="knowledge_index_jobs_generation_key"),
        Index(
            "knowledge_index_jobs_owner_document_created_idx",
            "workspace_id",
            "knowledge_base_id",
            "document_id",
            "created_at",
        ),
        Index(
            "knowledge_index_jobs_one_active_per_document_idx",
            "document_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    index_generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    chunking_config_version: Mapped[str] = mapped_column(String(128), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    claim_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
