"""Release metadata regression tests."""

import json
from importlib.metadata import version
from pathlib import Path

from click.testing import CliRunner

from app import __version__
from app.main import create_app
from cli.commands import cli

EXPECTED_VERSION = "0.10.0"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_python_and_fastapi_release_metadata_are_aligned() -> None:
    assert version("agentforge") == EXPECTED_VERSION
    assert __version__ == EXPECTED_VERSION
    assert create_app().version == EXPECTED_VERSION


def test_cli_reports_shared_release_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"agentforge, version {EXPECTED_VERSION}"


def test_frontend_package_uses_shared_release_version() -> None:
    package = json.loads((REPOSITORY_ROOT / "frontend" / "package.json").read_text())

    assert package["version"] == EXPECTED_VERSION
