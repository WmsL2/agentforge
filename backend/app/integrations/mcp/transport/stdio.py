"""stdio transport lifecycle for official MCP SDK clients."""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager, suppress

from mcp import Client, StdioServerParameters

from app.integrations.mcp.client.contract import MCPClient
from app.integrations.mcp.client.domain import MCPClientError
from app.integrations.mcp.client.implementations import MCPSDKClientAdapter


@asynccontextmanager
async def open_stdio_mcp_client(
    command: str,
    args: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
) -> AsyncIterator[MCPClient]:
    """Open an SDK stdio client and yield its AgentForge adapter."""
    parameters = StdioServerParameters(
        command=command,
        args=list(args),
        env=dict(env) if env is not None else None,
    )
    stack = AsyncExitStack()
    try:
        client = await stack.enter_async_context(Client(parameters))
    except Exception as error:
        await stack.aclose()
        raise MCPClientError(
            code="mcp_connection_failed",
            message=str(error) or type(error).__name__,
        ) from error

    try:
        yield MCPSDKClientAdapter(client)
    except BaseException:
        with suppress(Exception):
            await stack.aclose()
        raise
    else:
        try:
            await stack.aclose()
        except Exception as error:
            raise MCPClientError(
                code="mcp_connection_close_failed",
                message=str(error) or type(error).__name__,
            ) from error
