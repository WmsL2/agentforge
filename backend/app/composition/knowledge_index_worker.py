"""Per-task isolated composition for knowledge indexing."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, settings
from app.services.knowledge.chunking import ChunkingConfig
from app.services.knowledge.embedding import OpenAIEmbeddingProvider
from app.services.knowledge.indexing_service import KnowledgeIndexExecutor


@asynccontextmanager
async def open_knowledge_index_worker(
    worker_settings: Settings = settings,
) -> AsyncIterator[KnowledgeIndexExecutor]:
    engine = create_async_engine(worker_settings.DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def provider_factory() -> OpenAIEmbeddingProvider:
        return OpenAIEmbeddingProvider(
            api_key=worker_settings.EMBEDDING_API_KEY,
            model=worker_settings.EMBEDDING_MODEL,
            dimensions=worker_settings.EMBEDDING_DIMENSIONS,
            base_url=worker_settings.EMBEDDING_BASE_URL,
            batch_size=worker_settings.EMBEDDING_BATCH_SIZE,
            timeout_seconds=worker_settings.EMBEDDING_REQUEST_TIMEOUT_SECONDS,
            max_retries=worker_settings.EMBEDDING_MAX_RETRIES,
        )

    try:
        yield KnowledgeIndexExecutor(
            session_factory,
            provider_factory,
            chunking_config=ChunkingConfig(
                chunk_size=worker_settings.KNOWLEDGE_CHUNK_SIZE,
                overlap=worker_settings.KNOWLEDGE_CHUNK_OVERLAP,
                max_chunks=worker_settings.KNOWLEDGE_MAX_CHUNKS,
            ),
            lease_duration=timedelta(seconds=worker_settings.KNOWLEDGE_INDEX_LEASE_SECONDS),
        )
    finally:
        await engine.dispose()
