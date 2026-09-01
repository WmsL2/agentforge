"""Workflow-run application orchestration."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.application.definition.service import WorkflowService
from app.services.workflow.definition.serialization.serializer import (
    deserialize_workflow_graph,
    serialize_workflow_graph,
)
from app.services.workflow.execution.engine import WorkflowEngine, WorkflowExecutionValidationError
from app.services.workflow.execution.run.domain import WorkflowRun


class WorkflowRunService:
    """Coordinate ownership, synchronous execution, and run persistence."""

    def __init__(self, db: AsyncSession, workflow_service: WorkflowService, engine: WorkflowEngine):
        self.db = db
        self.workflow_service = workflow_service
        self.engine = engine

    @staticmethod
    def _definition_from_row(workflow_row: Any):
        return deserialize_workflow_graph(
            workflow_row.definition,
            workflow_id=workflow_row.id,
            name=workflow_row.name,
            description=workflow_row.description,
            revision=workflow_row.revision,
        )

    async def execute_workflow(self, workflow_id: UUID, user_id: UUID, input_data: dict[str, Any]):
        workflow_row = await self.workflow_service.get_owned_workflow(workflow_id, user_id)
        definition = self._definition_from_row(workflow_row)
        run = WorkflowRun(
            id=uuid4(),
            workflow_id=definition.id,
            workflow_revision=definition.revision,
            input=dict(input_data),
        )
        db_run = await run_repo.create_workflow_run(
            self.db,
            run=run,
            definition_snapshot=serialize_workflow_graph(definition),
        )
        try:
            await self.engine.execute(definition, run)
        except WorkflowExecutionValidationError as exception:
            raise ValidationError(
                details={
                    "issues": [
                        {
                            "code": issue.code.value,
                            "message": issue.message,
                            "node_id": issue.node_id,
                            "edge_id": issue.edge_id,
                        }
                        for issue in exception.validation_result.issues
                    ]
                }
            ) from exception
        return await run_repo.update_workflow_run_state(self.db, db_run=db_run, run=run)

    async def get_workflow_run(self, workflow_id: UUID, run_id: UUID, user_id: UUID):
        await self.workflow_service.get_owned_workflow(workflow_id, user_id)
        run = await run_repo.get_workflow_run_by_id(self.db, run_id)
        if run is None or run.workflow_id != workflow_id:
            raise NotFoundError(message="Workflow run not found")
        return run

    async def list_workflow_runs(
        self, workflow_id: UUID, user_id: UUID, skip: int = 0, limit: int = 50
    ):
        await self.workflow_service.get_owned_workflow(workflow_id, user_id)
        return (
            await run_repo.list_workflow_runs_by_workflow(
                self.db, workflow_id, skip=skip, limit=limit
            ),
            await run_repo.count_workflow_runs_by_workflow(self.db, workflow_id),
        )
