"""Tests for runtime configuration."""

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

import pytest
from pydantic import ValidationError
from redis.connection import parse_url as parse_redis_url
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import ConfigurationError, MCPStdioServerSettings, Settings, load_settings


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch, tmp_path):
    # Collection itself must already run under a synthetic environment; see report.
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENTFORGE_ENV_FILE", "none")
    monkeypatch.chdir(tmp_path)


def production_values():
    return {
        "ENVIRONMENT": "production",
        "SECRET_KEY": "synthetic-signing-key-01234567890123456789",
        "API_KEY": "synthetic-api-credential-0123456789",
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": 5432,
        "POSTGRES_USER": "synthetic_user",
        "POSTGRES_DB": "synthetic_db",
        "POSTGRES_PASSWORD": "synthetic-postgres-credential",
        "REDIS_HOST": "redis",
        "REDIS_PORT": 6379,
        "REDIS_DB": 0,
        "REDIS_PASSWORD": "synthetic-redis-credential",
        "FLOWER_USER": "operator",
        "FLOWER_PASSWORD": "synthetic-flower-credential",
        "DEBUG": False,
        "DB_ECHO": False,
        "CORS_ORIGINS": ["https://frontend.example.test"],
    }


def production(**overrides):
    return Settings(_env_file=None, **(production_values() | overrides))


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


def test_development_discovers_current_then_parent_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTFORGE_ENV_FILE")
    (tmp_path / ".env").write_text("PROJECT_NAME=parent\n", encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    assert Settings().PROJECT_NAME == "parent"
    (child / ".env").write_text("PROJECT_NAME=current\n", encoding="utf-8")
    assert Settings().PROJECT_NAME == "current"
    monkeypatch.setenv("PROJECT_NAME", "environment")
    assert Settings().PROJECT_NAME == "environment"
    assert Settings(PROJECT_NAME="constructor").PROJECT_NAME == "constructor"
    assert Settings(_env_file=None).PROJECT_NAME == "environment"


def test_production_never_discovers_development_file(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTFORGE_ENV_FILE")
    (tmp_path / ".env").write_text("PROJECT_NAME=forbidden\n", encoding="utf-8")
    assert Settings(**production_values()).PROJECT_NAME == "agentforge"
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ConfigurationError, match="CONFIGURATION_INVALID"):
        load_settings()
    with pytest.raises(ConfigurationError, match="DOWNGRADE"):
        Settings(_env_file=None, ENVIRONMENT="local")


def test_explicit_production_file_and_precedence(monkeypatch, tmp_path):
    env_file = tmp_path / "synthetic.prod"
    env_file.write_text(
        "\n".join(
            f"{key}={json.dumps(value) if isinstance(value, list) else str(value)}"
            for key, value in production_values().items()
        )
        + "\nPROJECT_NAME=file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTFORGE_ENV_FILE", str(env_file))
    assert Settings().ENVIRONMENT == "production"
    assert Settings().PROJECT_NAME == "file"
    monkeypatch.setenv("PROJECT_NAME", "environment")
    assert Settings().PROJECT_NAME == "environment"
    assert Settings(PROJECT_NAME="constructor").PROJECT_NAME == "constructor"
    monkeypatch.setenv("API_KEY", "")
    with pytest.raises(ConfigurationError):
        load_settings()
    # Explicit None isolates the file selector (but still reads process inputs).
    assert Settings(_env_file=None, ENVIRONMENT="local").PROJECT_NAME == "environment"


def test_production_file_preserves_literal_credentials(monkeypatch, tmp_path):
    env_file = tmp_path / "synthetic.prod"
    password = " literal-${MUST_NOT_EXPAND}-$-#-雪%40 "
    values = production_values() | {"POSTGRES_PASSWORD": password, "REDIS_PASSWORD": password}
    env_file.write_text(
        "\n".join(
            f"{key}='{json.dumps(value) if isinstance(value, list) else str(value)}'"
            for key, value in values.items()
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MUST_NOT_EXPAND", "forbidden-expansion")
    monkeypatch.setenv("AGENTFORGE_ENV_FILE", str(env_file))
    config = Settings()
    assert config.POSTGRES_PASSWORD == config.REDIS_PASSWORD == password
    assert make_url(config.DATABASE_URL).password == password
    assert parse_redis_url(config.REDIS_URL)["password"] == password


def test_explicit_production_selection_cannot_downgrade(monkeypatch, tmp_path):
    env_file = tmp_path / "synthetic.prod"
    env_file.write_text("ENVIRONMENT=local\n", encoding="utf-8")
    monkeypatch.setenv("AGENTFORGE_ENV_FILE", str(env_file))
    with pytest.raises(ConfigurationError):
        load_settings()
    monkeypatch.setenv("ENVIRONMENT", "local")
    with pytest.raises(ConfigurationError, match="SOURCE_INVALID"):
        load_settings()


def test_explicit_missing_file_and_development_file_in_production(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTFORGE_ENV_FILE", str(tmp_path / "missing.prod"))
    with pytest.raises(ConfigurationError):
        load_settings()
    with pytest.raises(ConfigurationError, match="DEVELOPMENT_ENV_FILE"):
        Settings(_env_file=tmp_path / ".env", **production_values())


REQUIRED = [
    "SECRET_KEY",
    "API_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "FLOWER_USER",
    "FLOWER_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_DB",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "DEBUG",
    "DB_ECHO",
    "CORS_ORIGINS",
]


@pytest.mark.parametrize("name", REQUIRED)
@pytest.mark.parametrize("kind", ["missing", "empty", "whitespace"])
def test_production_required_values_cannot_fall_back(name, kind):
    values = production_values()
    if kind == "missing":
        del values[name]
    else:
        values[name] = "" if kind == "empty" else "   "
    with pytest.raises((ValidationError, ConfigurationError)):
        Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "name",
    [
        "SECRET_KEY",
        "API_KEY",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "FLOWER_PASSWORD",
    ],
)
@pytest.mark.parametrize(
    "placeholder",
    [
        "postgres",
        "password",
        "admin",
        "change-me-in-production",
        "change-me-in-production-use-openssl-rand-hex-32",
        "replace-me",
        "your-api-key-here",
    ],
)
def test_production_rejects_known_credentials(name, placeholder):
    with pytest.raises(ValidationError):
        production(**{name: placeholder})


@pytest.mark.parametrize(
    "overrides",
    [
        {"SECRET_KEY": "short"},
        {"DEBUG": True},
        {"DB_ECHO": True},
        {"CORS_ORIGINS": ["*"]},
        {"CORS_ORIGINS": []},
        {"FLOWER_USER": "a:b"},
        {"FLOWER_USER": "a,b"},
        {"FLOWER_USER": "a b"},
        {"FLOWER_PASSWORD": "good:password"},
        {"FLOWER_PASSWORD": "good,password"},
        {"POSTGRES_PORT": 0},
        {"REDIS_PORT": 65536},
        {"REDIS_DB": -1},
        {"POSTGRES_HOST": "db/path"},
        {"REDIS_HOST": "redis://host"},
    ],
)
def test_production_flags_origins_flower_and_connection_validation(overrides):
    with pytest.raises(ValidationError):
        production(**overrides)


@pytest.mark.parametrize("host", ["db", "127.0.0.1", "::1", "[2001:db8::1]"])
def test_real_consumers_round_trip_reserved_credentials_without_connections(host):
    password = " @:/#%?雪%40 end "
    username = "user@:/#%? 雪"
    config = production(
        POSTGRES_USER=username,
        POSTGRES_PASSWORD=password,
        REDIS_PASSWORD=password,
        POSTGRES_HOST=host,
        REDIS_HOST=host,
        REDIS_DB=15,
        POSTGRES_PORT=5433,
        REDIS_PORT=6380,
    )
    expected_host = host.strip("[]")
    async_engine = create_async_engine(config.DATABASE_URL)
    sync_engine = create_engine(config.DATABASE_URL_SYNC)
    for engine in (async_engine, sync_engine):
        assert engine.url.username == username
        assert engine.url.password == password
        assert engine.url.host == expected_host
        assert engine.url.port == 5433
        assert engine.url.database == "synthetic_db"
        # Exercise actual asyncpg / psycopg2 dialect argument conversion, no connect.
        args, kwargs = engine.dialect.create_connect_args(engine.url)
        assert kwargs["password"] == password
        assert kwargs["user"] == username
    assert make_url(config.DATABASE_URL_SYNC).drivername == "postgresql"
    for url in (config.REDIS_URL, config.CELERY_BROKER_URL, config.CELERY_RESULT_BACKEND):
        parsed = parse_redis_url(url)
        assert parsed["password"] == password
        assert parsed["host"] == expected_host
        assert parsed["port"] == 6380
        assert parsed["db"] == 15


def test_development_celery_override_db15_and_passwordless_redis():
    config = Settings(_env_file=None, REDIS_HOST="redis")
    assert config.REDIS_URL == "redis://redis:6379/0"
    assert config.CELERY_BROKER_URL == config.CELERY_RESULT_BACKEND == config.REDIS_URL
    explicit = "redis://localhost:6379/15"
    config = Settings(_env_file=None, CELERY_BROKER_URL=explicit, CELERY_RESULT_BACKEND=explicit)
    assert config.CELERY_BROKER_URL == config.CELERY_RESULT_BACKEND == explicit


def test_local_empty_environment_keeps_existing_defaults(monkeypatch):
    monkeypatch.setenv("DEBUG", "")
    monkeypatch.setenv("POSTGRES_PORT", "")
    config = Settings(_env_file=None)
    assert config.DEBUG is False and config.POSTGRES_PORT == 5432


@pytest.mark.parametrize("name", ["CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"])
@pytest.mark.parametrize("override", ["", "redis://redis:6379/0", "redis://other:6379/15"])
def test_production_rejects_noncanonical_celery_overrides(name, override):
    with pytest.raises(ValidationError):
        production(**{name: override})


def test_production_accepts_only_exact_canonical_override():
    config = production()
    assert production(CELERY_BROKER_URL=config.REDIS_URL).CELERY_BROKER_URL == config.REDIS_URL


@pytest.mark.parametrize(
    "overrides",
    [
        {"LLM_API_KEY": " "},
        {"LLM_API_KEY": "your-api-key"},
        {"EMBEDDING_API_KEY": "change-me-in-production"},
        {"OPENAI_API_KEY": " "},
        {"LLM_API_KEY": "synthetic-key", "AI_MODEL": " "},
        {"EMBEDDING_API_KEY": "synthetic-key", "EMBEDDING_MODEL": ""},
        {"LLM_API_KEY": "synthetic-key", "LLM_PROVIDER": ""},
        {"LLM_BASE_URL": "ftp://host/v1"},
        {"LLM_BASE_URL": "https://user:password@host/v1"},
        {"EMBEDDING_BASE_URL": "https://host:wrong/v1"},
        {"LLM_BASE_URL": "not-a-url"},
        {"LLM_BASE_URL": "https://host/v1?key=secret"},
        {"LLM_BASE_URL": " "},
        {"EMBEDDING_DIMENSIONS": 768},
        {"KNOWLEDGE_AGENT_ENABLED": True},
        {"KNOWLEDGE_AGENT_ENABLED": True, "OPENAI_API_KEY": "synthetic-legacy-key"},
        {"KNOWLEDGE_AGENT_ENABLED": True, "LLM_API_KEY": "synthetic-key"},
    ],
)
def test_production_provider_configuration_invalid(overrides):
    with pytest.raises(ValidationError):
        production(**overrides)


def test_optional_providers_and_enabled_knowledge_agent():
    config = production()
    assert not config.LLM_API_KEY and not config.EMBEDDING_API_KEY
    config = production(
        KNOWLEDGE_AGENT_ENABLED=True,
        LLM_API_KEY="synthetic-runtime-key",
        EMBEDDING_API_KEY="synthetic-embedding-key",
        LLM_BASE_URL="https://custom.example.test:8443/v1",
        EMBEDDING_BASE_URL="http://[::1]:9000/v1",
    )
    assert config.KNOWLEDGE_AGENT_ENABLED
    assert config.LLM_API_KEY != config.EMBEDDING_API_KEY


@pytest.mark.parametrize(
    "name, value",
    [
        ("POSTGRES_PORT", "synthetic-secret-marker"),
        ("CORS_ORIGINS", "[synthetic-secret-marker"),
        ("MCP_STDIO_SERVERS", '[{"namespace":"x","command":{"synthetic-secret-marker":"value"}}]'),
        (
            "MCP_STDIO_SERVERS",
            '[{"namespace":"x","command":"x","env":{"synthetic-secret-marker":{}}}]',
        ),
        ("LLM_BASE_URL", "https://user:synthetic-secret-marker@host/v1"),
        ("EMBEDDING_API_KEY", "your-synthetic-secret-marker"),
    ],
)
def test_bootstrap_errors_do_not_disclose_values_or_chains(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError) as caught:
        load_settings(_env_file=None, **{k: v for k, v in production_values().items() if k != name})
    output = "".join(traceback.format_exception(caught.value))
    assert "synthetic-secret-marker" not in output
    assert "synthetic-signing-key" not in output
    assert "https://user:" not in output
    assert "input_value" not in output
    assert "CONFIGURATION_" in output
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "name, value",
    [
        ("CORS_ORIGINS", "[synthetic-startup-secret"),
        ("POSTGRES_PORT", "synthetic-startup-secret"),
        ("MCP_STDIO_SERVERS", '[{"namespace":"x","command":{"synthetic-startup-secret":1}}]'),
    ],
)
def test_actual_configuration_import_failure_is_safe(name, value):
    # A Python config import only: no application/server/service process is started.
    env = {
        key: val
        for key, val in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
    }
    env.update(AGENTFORGE_ENV_FILE="none", ENVIRONMENT="local", **{name: value})
    backend = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        env=env,
        cwd=backend,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "CONFIGURATION_" in output
    assert "synthetic-startup-secret" not in output
    assert "input_value" not in output


def test_tracked_production_yaml_roles_and_infrastructure_share_configuration():
    import yaml

    root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((root / "docker-compose.prod.yml").read_text(encoding="utf-8"))
    common = config["x-production-environment"]
    for role in ("app", "celery_worker", "celery_beat", "flower"):
        service = config["services"][role]
        assert service["env_file"] == ["./backend/.env.prod"]
        for name, value in common.items():
            assert service["environment"][name] == value
        assert service["environment"]["ENVIRONMENT"] == "production"
        assert "CELERY_BROKER_URL" not in service["environment"]
        assert "CELERY_RESULT_BACKEND" not in service["environment"]
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert config["services"]["db"]["environment"][name] == common[name]
    redis_command = config["services"]["redis"]["command"]
    assert isinstance(redis_command, list)
    assert redis_command[redis_command.index("--requirepass") + 1] == common["REDIS_PASSWORD"]
    for line in (root / "Makefile").read_text(encoding="utf-8").splitlines():
        if "docker compose" in line and "docker-compose.prod.yml" in line:
            assert "--env-file backend/.env.prod" in line
