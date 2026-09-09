"""LangChain adapter for AgentForge Tool Platform definitions."""

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from app.services.tool import ToolDefinition, ToolExecutionRequest, ToolExecutionService


class LangGraphToolAdapter:
    """Adapt AgentForge tool definitions to LangChain StructuredTool instances."""

    def __init__(self, execution_service: ToolExecutionService) -> None:
        self._execution_service = execution_service

    def adapt(self, definition: ToolDefinition) -> BaseTool:
        """Create a StructuredTool that executes through the Tool Platform."""

        async def execute_tool(**arguments: Any) -> Any:
            result = await self._execution_service.execute(
                ToolExecutionRequest(
                    tool_name=definition.name,
                    arguments=arguments,
                )
            )
            return result.output

        return StructuredTool.from_function(
            func=None,
            coroutine=execute_tool,
            name=definition.name,
            description=definition.description,
            args_schema=dict(definition.input_schema),
            infer_schema=False,
        )
