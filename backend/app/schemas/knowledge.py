"""HTTP schemas for workspace-scoped knowledge bases."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

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
