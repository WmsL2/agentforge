"""Embedding provider contracts and production adapter."""

from app.services.knowledge.embedding.provider import (
    EmbeddingError,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
)

__all__ = ["EmbeddingError", "EmbeddingProvider", "OpenAIEmbeddingProvider"]
