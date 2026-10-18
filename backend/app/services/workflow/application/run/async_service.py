"""Asynchronous workflow-run submission orchestration."""

import logging
from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ExternalServiceError, ValidationError
from app.repositories.workflow.run import repository as run_repo
from app.services.workflow.application.background import (
    WorkflowExecutionDispatcher,
    WorkflowExecutionJob,
)
from app.services.workflow.application.definition.service import WorkflowService
from app.services.workflow.definition.serialization.serializer import (
    deserialize_workflow_graph,
    serialize_workflow_graph,
)
from app.services.workflow.definition.validation.validator import WorkflowValidator
from app.services.workflow.execution.run.domain import WorkflowRun
from app.services.workspace.domain import WorkspacePermission

logger = logging.getLogger(__name__)


class WorkflowAsyncRunService:
    """Persist an authorized PENDING run before publishing its execution job."""

    def __init__(
        self,
        db: AsyncSession,
        workflow_service: WorkflowService,
        dispatcher: WorkflowExecutionDispatcher,
    ) -> None:
        self._db = db
        self._workflow_service = workflow_service
        self._dispatcher = dispatcher

    async def submit_workflow(
        self,
        workflow_id: UUID,
        actor_user_id: UUID,
        input_data: dict[str, Any],
    ):
        workflow_row = await self._workflow_service.get_authorized_workflow(
            workflow_id,
            actor_user_id,
            WorkspacePermission.WORKFLOW_RUN,
        )
        definition = deserialize_workflow_graph(
            workflow_row.definition,
            workflow_id=workflow_row.id,
            name=workflow_row.name,
            description=workflow_row.description,
            revision=workflow_row.revision,
        )
        validation = WorkflowValidator().validate(definition)
        if not validation.is_valid:
            raise ValidationError(
                details={
                    "issues": [
                        {
                            "code": issue.code.value,
                            "message": issue.message,
                            "node_id": issue.node_id,
                            "edge_id": issue.edge_id,
                        }
                        for issue in validation.issues
                    ]
                }
            )

        run = WorkflowRun(
            id=uuid4(),
            workflow_id=definition.id,
            workflow_revision=definition.revision,
            input=deepcopy(input_data),
        )
        snapshot = deepcopy(serialize_workflow_graph(definition))
        try:
            db_run = await run_repo.create_workflow_run(
                self._db,
                run=run,
                definition_snapshot=snapshot,
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise

        try:
            await self._dispatcher.dispatch(WorkflowExecutionJob(run.id))
        except Exception as error:
            logger.error(
                "workflow_dispatch_not_confirmed",
                extra={"run_id": str(run.id), "exception_type": type(error).__name__},
            )
            raise ExternalServiceError(
                message="Workflow run was created, but task dispatch could not be confirmed.",
                code="WORKFLOW_DISPATCH_FAILED",
                details={"run_id": str(run.id)},
            ) from error
        return db_run
