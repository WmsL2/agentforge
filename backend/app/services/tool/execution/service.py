"""Unified execution boundary for Tool Platform requests."""

from app.services.tool.definition.validation import (
    ToolSchemaValidationIssue,
    ToolSchemaValidator,
)
from app.services.tool.execution.domain import (
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from app.services.tool.registry import ToolRegistry, ToolRegistryError


class ToolExecutionService:
    """Resolve, validate, and execute one registered tool invocation."""

    def __init__(self, registry: ToolRegistry, validator: ToolSchemaValidator) -> None:
        self._registry = registry
        self._validator = validator

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """Resolve, validate, and execute ``request`` through the Tool Platform."""
        try:
            registration = self._registry.resolve(request.tool_name)
        except ToolRegistryError as error:
            raise ToolExecutionError(
                code=error.code.value,
                message=error.message,
                retryable=False,
            ) from error

        validation_result = self._validator.validate_arguments(
            registration.definition,
            request.arguments,
        )
        if not validation_result.is_valid:
            first_issue = validation_result.issues[0]
            raise ToolExecutionError(
                code=first_issue.code.value,
                message=self._format_validation_issues(validation_result.issues),
                retryable=False,
            )

        try:
            return await registration.executor.execute(request)
        except ToolExecutionError:
            raise
        except Exception as error:
            raise ToolExecutionError(
                code="tool_execution_failed",
                message=str(error) or type(error).__name__,
                retryable=False,
            ) from error

    @staticmethod
    def _format_validation_issues(issues: tuple[ToolSchemaValidationIssue, ...]) -> str:
        """Render every deterministic validation issue into one error message."""
        return "; ".join(
            f"{'.'.join(str(component) for component in issue.path)}: {issue.message}"
            if issue.path
            else issue.message
            for issue in issues
        )
