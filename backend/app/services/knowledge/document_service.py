"""Document application service with authorization and storage compensation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ContentUnavailableError, NotFoundError
from app.repositories import knowledge as knowledge_repo
from app.repositories import knowledge_document as document_repo
from app.services.knowledge.document_parser import KnowledgeDocumentParser, ParsedDocument
from app.services.knowledge.document_storage import KnowledgeDocumentStorage
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspacePermission

logger = logging.getLogger(__name__)

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
PARSER_TIMEOUT_SECONDS = 30
_PARSER_SLOTS = asyncio.Semaphore(4)


def _release_parser_slot(task: asyncio.Task[ParsedDocument]) -> None:
    _PARSER_SLOTS.release()
    if not task.cancelled():
        task.exception()


class KnowledgeDocumentService:
    """Coordinate document parsing, durable metadata, and private files."""

    def __init__(
        self,
        db: AsyncSession,
        authorization: WorkspaceAuthorizationService,
        storage: KnowledgeDocumentStorage,
        parser: KnowledgeDocumentParser,
    ):
        self._db = db
        self._authorization = authorization
        self._storage = storage
        self._parser = parser

    async def upload_document(
        self,
        workspace_id: UUID,
        knowledge_base_id: UUID,
        actor_user_id: UUID,
        upload: UploadFile,
    ):
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.KNOWLEDGE_EDIT
        )
        await self._require_knowledge_base(workspace_id, knowledge_base_id)
        filename = self._storage.sanitize_filename(upload.filename or "")
        mime_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
        try:
            data = await upload.read(MAX_DOCUMENT_BYTES + 1)
        finally:
            await upload.close()
        if len(data) > MAX_DOCUMENT_BYTES:
            raise BadRequestError(
                message="Document exceeds the 10 MiB upload limit",
                code="DOCUMENT_TOO_LARGE",
            )
        parsed = await self._parse_bounded(data=data, filename=filename, mime_type=mime_type)
        document_id = uuid4()
        storage_path = self._storage.build_storage_path(
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            filename=filename,
        )
        await self._storage.save(storage_path, data)
        try:
            document = await document_repo.create(
                self._db,
                document_id=document_id,
                workspace_id=workspace_id,
                knowledge_base_id=knowledge_base_id,
                created_by_user_id=actor_user_id,
                filename=filename,
                mime_type=mime_type,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                storage_path=storage_path,
                parsed=parsed,
            )
            # This endpoint owns its transaction so a commit failure can compensate
            # the already-written private file before a success response is emitted.
            await self._db.commit()
            return document
        except BaseException:
            await self._rollback_safely()
            try:
                await self._storage.delete(storage_path)
            except Exception:
                logger.error(
                    "Document upload compensation failed; orphan reconciliation required",
                    extra={"document_id": str(document_id)},
                )
            raise

    async def list_documents(
        self,
        workspace_id: UUID,
        knowledge_base_id: UUID,
        actor_user_id: UUID,
        *,
        skip: int,
        limit: int,
    ):
        await self._authorize_read_and_require_base(workspace_id, knowledge_base_id, actor_user_id)
        items = await document_repo.list_scoped(
            self._db,
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            skip=skip,
            limit=limit,
        )
        total = await document_repo.count_scoped(
            self._db, workspace_id=workspace_id, knowledge_base_id=knowledge_base_id
        )
        return items, total

    async def get_document(
        self, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID, actor_user_id: UUID
    ):
        await self._authorize_read_and_require_base(workspace_id, knowledge_base_id, actor_user_id)
        return await self._get_or_404(workspace_id, knowledge_base_id, document_id)

    async def get_content(
        self, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID, actor_user_id: UUID
    ):
        document = await self.get_document(
            workspace_id, knowledge_base_id, document_id, actor_user_id
        )
        if document.parse_status != "ready" or document.parsed_content is None:
            raise ContentUnavailableError(
                message="Parsed document content is unavailable",
                code="DOCUMENT_CONTENT_UNAVAILABLE",
            )
        return document

    async def get_download(
        self, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID, actor_user_id: UUID
    ):
        document = await self.get_document(
            workspace_id, knowledge_base_id, document_id, actor_user_id
        )
        path = await self._storage.resolve_for_download(document.storage_path)
        return document, path

    async def delete_document(
        self, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID, actor_user_id: UUID
    ) -> None:
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.KNOWLEDGE_EDIT
        )
        await self._require_knowledge_base(workspace_id, knowledge_base_id)
        document = await self._get_or_404(workspace_id, knowledge_base_id, document_id)
        storage_path = document.storage_path
        await document_repo.delete(self._db, document=document)
        await self._db.commit()
        try:
            await self._storage.delete(storage_path)
        except Exception:
            # The row is already gone, so the private file cannot be downloaded.
            # A later reconciliation pass removes this crash/failure residue.
            logger.error(
                "Document file cleanup failed; orphan reconciliation required",
                extra={"document_id": str(document_id)},
            )

    async def reconcile_orphans(self) -> int:
        """Remove files with no database row; intended for maintenance/startup jobs."""
        return await self._storage.reconcile_orphans(
            await document_repo.all_storage_paths(self._db)
        )

    async def _authorize_read_and_require_base(
        self, workspace_id: UUID, knowledge_base_id: UUID, actor_user_id: UUID
    ) -> None:
        await self._authorization.require_permission(
            workspace_id, actor_user_id, WorkspacePermission.KNOWLEDGE_READ
        )
        await self._require_knowledge_base(workspace_id, knowledge_base_id)

    async def _require_knowledge_base(self, workspace_id: UUID, knowledge_base_id: UUID):
        knowledge_base = await knowledge_repo.get_by_workspace_and_id(
            self._db, workspace_id=workspace_id, knowledge_base_id=knowledge_base_id
        )
        if knowledge_base is None:
            raise NotFoundError(message="Knowledge base not found")
        return knowledge_base

    async def _get_or_404(self, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID):
        document = await document_repo.get_scoped(
            self._db,
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
        if document is None:
            raise NotFoundError(message="Knowledge document not found")
        return document

    async def _rollback_safely(self) -> None:
        try:
            await self._db.rollback()
        except Exception:
            logger.exception("Document transaction rollback failed")

    async def _parse_bounded(self, *, data: bytes, filename: str, mime_type: str):
        """Keep timed-out parser threads counted until they really finish."""
        await _PARSER_SLOTS.acquire()
        task = asyncio.create_task(
            asyncio.to_thread(
                self._parser.parse,
                data=data,
                filename=filename,
                mime_type=mime_type,
            )
        )
        release_now = True
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=PARSER_TIMEOUT_SECONDS)
        except TimeoutError:
            release_now = False
            task.add_done_callback(_release_parser_slot)
            return ParsedDocument("failed", None, "DOCUMENT_PARSE_TIMEOUT", None, {})
        except asyncio.CancelledError:
            release_now = False
            task.add_done_callback(_release_parser_slot)
            raise
        finally:
            if release_now:
                _PARSER_SLOTS.release()
