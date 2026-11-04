"""Knowledge base application service."""

from app.services.knowledge.document_service import KnowledgeDocumentService
from app.services.knowledge.service import KnowledgeBaseService

__all__ = ["KnowledgeBaseService", "KnowledgeDocumentService"]
