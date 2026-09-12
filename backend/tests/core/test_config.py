"""Tests for MCP stdio configuration."""

from app.core.config import MCPStdioServerSettings, Settings


def test_mcp_stdio_servers_default_to_an_empty_list() -> None:
    assert Settings().MCP_STDIO_SERVERS == []


def test_mcp_stdio_server_settings_accept_structured_values() -> None:
    settings = Settings(
        MCP_STDIO_SERVERS=[
            {
                "namespace": "github",
                "command": "github-mcp",
                "args": ["--serve"],
                "env": {"TOKEN": "test"},
            }
        ]
    )

    assert [
        MCPStdioServerSettings(
            namespace="github",
            command="github-mcp",
            args=["--serve"],
            env={"TOKEN": "test"},
        )
    ] == settings.MCP_STDIO_SERVERS
