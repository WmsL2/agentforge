"""Real PostgreSQL + pgvector proofs for the request-scoped Knowledge Agent."""

import asyncio
import hashlib
import os
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.db.models.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeIndexJob,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMembership
from app.repositories import knowledge as knowledge_repo
from app.repositories import workspace as workspace_repo
from app.services.agent_runtime.runner.implementations import LangGraphAgentRunner
from app.services.knowledge.agent_service import KnowledgeAgentService
from app.services.knowledge.retrieval_service import KnowledgeRetrievalService
from app.services.workspace import WorkspaceRole

DATABASE = "agentforge_v011_atomic5_verify"
MODEL = "text-embedding-3-small"
DIMENSIONS = 1536


class DeterministicEmbeddingProvider:
    model = MODEL
    dimensions = DIMENSIONS

    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.calls: list[list[str]] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [self.vector.copy() for _ in texts]


class ScriptedModel:
    def __init__(self, query: str, answer: str) -> None:
        self._responses = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge_search",
                        "args": {"query": query, "top_k": 5},
                        "id": f"call-{uuid4().hex}",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content=answer),
        ]
        self.calls = 0

    def bind_tools(self, tools):
        assert [tool.name for tool in tools] == ["knowledge_search"]
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return self._responses.pop(0)


@dataclass(frozen=True)
class Scope:
    owner_id: UUID
    workspace_id: UUID
    knowledge_base_id: UUID


def _unit_vector(first: float = 1.0, second: float = 0.0) -> list[float]:
    return [first, second] + [0.0] * (DIMENSIONS - 2)


def _retrieval(factory, provider) -> KnowledgeRetrievalService:
    return KnowledgeRetrievalService(
        cast(Any, factory),
        lambda: provider,
        embedding_model=MODEL,
        embedding_dimensions=DIMENSIONS,
        embedding_timeout_seconds=2,
        db_statement_timeout_ms=5000,
    )


def _agent(retrieval, model: ScriptedModel) -> KnowledgeAgentService:
    def runner_factory(tools, recursion_limit):
        return LangGraphAgentRunner(
            model_factory=lambda _: model,
            tools=tools,
            recursion_limit=recursion_limit,
        )

    return KnowledgeAgentService(
        retrieval,
        runner_factory,
        enabled=True,
        timeout_seconds=5,
        maximum_tool_calls=2,
        model_api_key_configured=True,
    )


async def _create_scope(factory, name: str) -> Scope:
    owner_id = uuid4()
    async with factory() as session, session.begin():
        session.add(User(id=owner_id, email=f"atomic5-{owner_id.hex}@example.invalid"))
        await session.flush()
        workspace = await workspace_repo.create_workspace(
            session, name=name, created_by_user_id=owner_id
        )
        await workspace_repo.create_membership(
            session,
            workspace_id=workspace.id,
            user_id=owner_id,
            role=WorkspaceRole.OWNER,
        )
        base = await knowledge_repo.create(
            session,
            workspace_id=workspace.id,
            name=f"{name} knowledge",
            description=None,
            created_by_user_id=owner_id,
        )
    return Scope(owner_id, workspace.id, base.id)


async def _add_generation(
    session,
    scope: Scope,
    *,
    filename: str,
    content: str,
    vector: list[float],
    document_id: UUID | None = None,
) -> tuple[UUID, UUID]:
    document_id = document_id or uuid4()
    generation_id = uuid4()
    document = await session.get(KnowledgeDocument, document_id)
    if document is None:
        document = KnowledgeDocument(
            id=document_id,
            workspace_id=scope.workspace_id,
            knowledge_base_id=scope.knowledge_base_id,
            created_by_user_id=scope.owner_id,
            filename=filename,
            mime_type="text/plain",
            size_bytes=len(content.encode()),
            sha256=hashlib.sha256(content.encode()).hexdigest(),
            storage_path=f"{scope.workspace_id}/{scope.knowledge_base_id}/{document_id}/{filename}",
            parse_status="ready",
            parsed_content=content,
            page_count=1,
            parse_metadata={"format": "txt"},
        )
        session.add(document)
        await session.flush()
    session.add(
        KnowledgeIndexJob(
            workspace_id=scope.workspace_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=document_id,
            index_generation_id=generation_id,
            status="succeeded",
            embedding_model=MODEL,
            embedding_dimensions=DIMENSIONS,
            chunking_config_version="character-v1:1000:150:2500",
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            attempt_count=1,
            claim_generation=1,
            chunk_count=1,
        )
    )
    chunk_id = uuid4()
    session.add(
        KnowledgeDocumentChunk(
            id=chunk_id,
            workspace_id=scope.workspace_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=document_id,
            index_generation_id=generation_id,
            chunk_index=0,
            content=content,
            start_offset=0,
            end_offset=len(content),
            page_start=1,
            page_end=1,
            chunk_metadata={},
            embedding_model=MODEL,
            embedding=vector,
        )
    )
    document.active_index_generation_id = generation_id
    await session.flush()
    return document_id, chunk_id


async def _cleanup(factory, scopes: list[Scope]) -> None:
    async with factory() as session, session.begin():
        for scope in scopes:
            await session.execute(delete(Workspace).where(Workspace.id == scope.workspace_id))
            await session.execute(delete(User).where(User.id == scope.owner_id))


@pytest.fixture
def atomic5_factory(postgres_restart_session_factory):
    if os.getenv("AGENTFORGE_RUN_ATOMIC5_E2E") != "1":
        pytest.skip("Set AGENTFORGE_RUN_ATOMIC5_E2E=1 to run Atomic 5 PostgreSQL proofs.")
    if settings.POSTGRES_DB != DATABASE:
        pytest.skip(f"Atomic 5 proof requires POSTGRES_DB={DATABASE}.")
    return postgres_restart_session_factory


@pytest.mark.anyio
async def test_real_langgraph_tool_pgvector_current_generation_and_no_writes(
    atomic5_factory,
) -> None:
    factory = atomic5_factory
    target = await _create_scope(factory, "Atomic 5 target")
    foreign = await _create_scope(factory, "Atomic 5 foreign")
    try:
        document_id = uuid4()
        async with factory() as session, session.begin():
            _, old_chunk = await _add_generation(
                session,
                target,
                filename="target.txt",
                content="old inactive evidence",
                vector=_unit_vector(),
                document_id=document_id,
            )
            _, current_chunk = await _add_generation(
                session,
                target,
                filename="target.txt",
                content="current workspace evidence",
                vector=_unit_vector(),
                document_id=document_id,
            )
            _, foreign_chunk = await _add_generation(
                session,
                foreign,
                filename="foreign.txt",
                content="foreign evidence",
                vector=_unit_vector(),
            )
        async with factory() as session:
            before = (
                await session.scalar(select(func.count()).select_from(KnowledgeIndexJob)),
                await session.scalar(select(func.count()).select_from(KnowledgeDocumentChunk)),
            )

        provider = DeterministicEmbeddingProvider(_unit_vector())
        model = ScriptedModel("current", "Grounded answer")
        result = await _agent(_retrieval(factory, provider), model).ask(
            target.workspace_id,
            target.knowledge_base_id,
            target.owner_id,
            "What is current?",
        )

        assert result.status == "answered"
        assert [source.chunk_id for source in result.sources] == [current_chunk]
        assert old_chunk not in [source.chunk_id for source in result.sources]
        assert foreign_chunk not in [source.chunk_id for source in result.sources]
        assert provider.calls == [["current"]]
        assert model.calls == 2
        async with factory() as session:
            after = (
                await session.scalar(select(func.count()).select_from(KnowledgeIndexJob)),
                await session.scalar(select(func.count()).select_from(KnowledgeDocumentChunk)),
            )
        assert after == before
    finally:
        await _cleanup(factory, [target, foreign])


@pytest.mark.anyio
async def test_concurrent_request_isolation_and_membership_revocation(atomic5_factory) -> None:
    factory = atomic5_factory
    first = await _create_scope(factory, "Atomic 5 concurrent A")
    second = await _create_scope(factory, "Atomic 5 concurrent B")
    try:
        async with factory() as session, session.begin():
            _, first_chunk = await _add_generation(
                session,
                first,
                filename="a.txt",
                content="workspace A",
                vector=_unit_vector(),
            )
            _, second_chunk = await _add_generation(
                session,
                second,
                filename="b.txt",
                content="workspace B",
                vector=_unit_vector(),
            )

        first_model = ScriptedModel("a", "A answer")
        second_model = ScriptedModel("b", "B answer")
        first_agent = _agent(
            _retrieval(factory, DeterministicEmbeddingProvider(_unit_vector())), first_model
        )
        second_agent = _agent(
            _retrieval(factory, DeterministicEmbeddingProvider(_unit_vector())), second_model
        )
        first_result, second_result = await asyncio.gather(
            first_agent.ask(
                first.workspace_id, first.knowledge_base_id, first.owner_id, "question A"
            ),
            second_agent.ask(
                second.workspace_id, second.knowledge_base_id, second.owner_id, "question B"
            ),
        )
        assert [source.chunk_id for source in first_result.sources] == [first_chunk]
        assert [source.chunk_id for source in second_result.sources] == [second_chunk]

        async with factory() as session, session.begin():
            await session.execute(
                delete(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == first.workspace_id,
                    WorkspaceMembership.user_id == first.owner_id,
                )
            )
        revoked_model = ScriptedModel("a", "must not execute")
        revoked_agent = _agent(
            _retrieval(factory, DeterministicEmbeddingProvider(_unit_vector())), revoked_model
        )
        with pytest.raises(NotFoundError):
            await revoked_agent.ask(
                first.workspace_id, first.knowledge_base_id, first.owner_id, "revoked"
            )
        assert revoked_model.calls == 0
    finally:
        await _cleanup(factory, [first, second])
