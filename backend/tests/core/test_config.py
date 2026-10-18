"""Tests for runtime configuration."""

import pytest
from pydantic import ValidationError

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


def test_workflow_background_lease_defaults_to_900_seconds() -> None:
    assert Settings(_env_file=None).WORKFLOW_BACKGROUND_LEASE_SECONDS == 900


@pytest.mark.parametrize("seconds", [0, -1])
def test_workflow_background_lease_must_be_strictly_positive(seconds: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, WORKFLOW_BACKGROUND_LEASE_SECONDS=seconds)


def test_workflow_background_lease_accepts_a_positive_value() -> None:
    assert (
        Settings(
            _env_file=None, WORKFLOW_BACKGROUND_LEASE_SECONDS=42
        ).WORKFLOW_BACKGROUND_LEASE_SECONDS
        == 42
    )
