"""HTTP schemas for workspace-scoped knowledge bases."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import BaseSchema


class KnowledgeBaseCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class KnowledgeBaseUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null_name(cls, data: Any) -> Any:
        """A missing name is a no-op, while an explicit null is invalid."""
        if isinstance(data, dict) and "name" in data and data["name"] is None:
            raise ValueError("name cannot be null")
        return data


class KnowledgeBaseRead(BaseSchema):
    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime | None


class KnowledgeBaseList(BaseSchema):
    items: list[KnowledgeBaseRead]
    total: int


class KnowledgeDocumentRead(BaseSchema):
    id: UUID
    workspace_id: UUID
    knowledge_base_id: UUID
    created_by_user_id: UUID | None
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    parse_status: str
    parse_error_code: str | None
    page_count: int | None
    parse_metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime | None


class KnowledgeDocumentList(BaseSchema):
    items: list[KnowledgeDocumentRead]
    total: int


class KnowledgeDocumentContent(BaseSchema):
    document_id: UUID
    content: str
    page_count: int | None
    parse_metadata: dict[str, object]


class KnowledgeIndexJobRead(BaseSchema):
    id: UUID
    document_id: UUID
    status: str
    embedding_model: str
    embedding_dimensions: int
    index_generation_id: UUID
    chunking_config_version: str
    attempt_count: int
    error_code: str | None
    created_at: datetime


class KnowledgeIndexStatusRead(BaseSchema):
    document_id: UUID
    job_id: UUID | None
    status: str
    active_generation_id: UUID | None
    chunk_count: int
    embedding_model: str | None
    index_version: str | None
    error_code: str | None


class KnowledgeSearchRequest(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=-1.0, le=1.0)


class KnowledgeSearchItemRead(BaseSchema):
    chunk_id: UUID
    document_id: UUID
    knowledge_base_id: UUID
    filename: str
    chunk_index: int
    content: str
    start_offset: int
    end_offset: int
    page_start: int | None
    page_end: int | None
    similarity_score: float


class KnowledgeSearchResponse(BaseSchema):
    query: str
    results: list[KnowledgeSearchItemRead]
    total: int
    embedding_model: str


class KnowledgeAskRequest(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)


class KnowledgeAgentSourceRead(BaseSchema):
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_start: int | None
    page_end: int | None
    similarity_score: float


class KnowledgeAskResponse(BaseSchema):
    answer: str
    status: Literal["answered", "no_evidence"]
    sources: list[KnowledgeAgentSourceRead]
