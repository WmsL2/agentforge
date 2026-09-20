"""Release metadata regression tests."""

from click.testing import CliRunner

from app import __version__
from app.main import create_app
from cli.commands import cli


def test_release_metadata_is_v070() -> None:
    assert __version__ == "0.7.0"
    assert create_app().version == "0.7.0"


def test_cli_reports_v070() -> None:
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "0.7.0" in result.output
