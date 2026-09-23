"""Workflow CRUD application service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.repositories import workflow as workflow_repo
from app.services.workflow.definition.model.domain import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
)
from app.services.workflow.definition.serialization.serializer import serialize_workflow_graph
from app.services.workflow.definition.validation.validator import WorkflowValidator
from app.services.workspace.authorization import WorkspaceAuthorizationService
from app.services.workspace.domain import WorkspacePermission

if TYPE_CHECKING:
    from app.schemas.workflow.definition import WorkflowCreate, WorkflowGraphSchema, WorkflowUpdate


class WorkflowService:
    def __init__(self, db: AsyncSession, authorization: WorkspaceAuthorizationService | None = None):
        self.db = db
        self._authorization = authorization

    def _require_authorization(self) -> WorkspaceAuthorizationService:
        if self._authorization is None:
            raise RuntimeError("WorkflowService authorization is required for Workspace-scoped CRUD")
        return self._authorization

    def _definition(
        self,
        graph: WorkflowGraphSchema,
        *,
        workflow_id: UUID,
        name: str,
        description: str | None,
        revision: int,
    ) -> WorkflowDefinition:
        return WorkflowDefinition(
            workflow_id,
            name,
            graph.entry_node_id,
            description,
            tuple(WorkflowNode(n.id, n.kind, n.config, n.metadata) for n in graph.nodes),
            tuple(
                WorkflowEdge(e.id, e.source, e.target, e.condition, e.metadata) for e in graph.edges
            ),
            graph.metadata,
            graph.schema_version,
            revision,
        )

    def _validate(self, definition: WorkflowDefinition) -> None:
        result = WorkflowValidator().validate(definition)
        if not result.is_valid:
            raise ValidationError(
                details={
                    "issues": [
                        {
                            "code": i.code.value,
                            "message": i.message,
                            "node_id": i.node_id,
                            "edge_id": i.edge_id,
                        }
                        for i in result.issues
                    ]
                }
            )

    async def get_owned_workflow(self, workflow_id: UUID, user_id: UUID):
        """Legacy creator boundary retained for Atomic 6 Run/Approval compatibility."""
        row = await workflow_repo.get_workflow_by_id(self.db, workflow_id)
        if row is None or row.user_id != user_id:
            raise NotFoundError(message="Workflow not found")
        return row

    async def get_authorized_workflow(
        self, workflow_id: UUID, actor_user_id: UUID, permission: WorkspacePermission
    ):
        row = await workflow_repo.get_workflow_by_id(self.db, workflow_id)
        if row is None or row.workspace_id is None:
            raise NotFoundError(message="Workflow not found")
        try:
            await self._require_authorization().require_permission(
                row.workspace_id, actor_user_id, permission
            )
        except NotFoundError:
            raise NotFoundError(message="Workflow not found") from None
        return row

    async def create_workflow(self, workspace_id: UUID, actor_user_id: UUID, data: WorkflowCreate):
        await self._require_authorization().require_permission(
            workspace_id, actor_user_id, WorkspacePermission.WORKFLOW_CREATE
        )
        definition = self._definition(
            data.definition,
            workflow_id=uuid4(),
            name=data.name,
            description=data.description,
            revision=1,
        )
        self._validate(definition)
        return await workflow_repo.create_workflow(
            self.db,
            workflow_id=definition.id,
            user_id=actor_user_id,
            workspace_id=workspace_id,
            name=data.name,
            description=data.description,
            definition=serialize_workflow_graph(definition),
            revision=1,
        )

    async def get_workflow(self, workflow_id: UUID, actor_user_id: UUID):
        return await self.get_authorized_workflow(
            workflow_id, actor_user_id, WorkspacePermission.WORKFLOW_READ
        )

    async def list_workflows(self, workspace_id: UUID, actor_user_id: UUID, skip: int = 0, limit: int = 50):
        await self._require_authorization().require_permission(
            workspace_id, actor_user_id, WorkspacePermission.WORKFLOW_READ
        )
        return await workflow_repo.list_workflows_by_workspace(
            self.db, workspace_id, skip=skip, limit=limit
        ), await workflow_repo.count_workflows_by_workspace(self.db, workspace_id)

    async def update_workflow(self, workflow_id: UUID, actor_user_id: UUID, data: WorkflowUpdate):
        row = await self.get_authorized_workflow(
            workflow_id, actor_user_id, WorkspacePermission.WORKFLOW_EDIT
        )
        supplied = data.model_fields_set
        if not supplied:
            return row
        if data.definition is not None:
            graph = data.definition
        else:
            from app.schemas.workflow.definition import WorkflowGraphSchema

            graph = WorkflowGraphSchema.model_validate(row.definition)
        definition = self._definition(
            graph,
            workflow_id=row.id,
            name=data.name if data.name is not None else row.name,
            description=data.description if "description" in supplied else row.description,
            revision=row.revision + 1,
        )
        self._validate(definition)
        return await workflow_repo.update_workflow(
            self.db,
            db_workflow=row,
            update_data={
                "name": definition.name,
                "description": definition.description,
                "definition": serialize_workflow_graph(definition),
                "revision": definition.revision,
            },
        )

    async def delete_workflow(self, workflow_id: UUID, actor_user_id: UUID) -> None:
        await self.get_authorized_workflow(
            workflow_id, actor_user_id, WorkspacePermission.WORKFLOW_DELETE
        )
        await workflow_repo.delete_workflow(self.db, workflow_id)

    def validate_definition(self, graph: WorkflowGraphSchema):
        return WorkflowValidator().validate(
            self._definition(
                graph, workflow_id=uuid4(), name="validation", description=None, revision=1
            )
        )
