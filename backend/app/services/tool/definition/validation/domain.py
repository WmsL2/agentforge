"""Pure domain contracts for tool JSON Schema validation."""

from dataclasses import dataclass
from enum import Enum


class ToolSchemaValidationCode(str, Enum):  # noqa: UP042
    """Stable machine-readable outcomes for tool schema validation."""

    INVALID_INPUT_SCHEMA = "invalid_input_schema"
    INVALID_ARGUMENTS = "invalid_arguments"


@dataclass(frozen=True)
class ToolSchemaValidationIssue:
    """One schema or argument validation problem."""

    code: ToolSchemaValidationCode
    message: str
    path: tuple[str | int, ...] = ()


@dataclass(frozen=True)
class ToolSchemaValidationResult:
    """The complete result of schema or argument validation."""

    issues: tuple[ToolSchemaValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Whether validation produced no issues."""
        return self.issues == ()
