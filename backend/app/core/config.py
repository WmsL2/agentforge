"""Application configuration using Pydantic BaseSettings."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

import ipaddress
import os
import re
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import quote, urlsplit

from dotenv import dotenv_values
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
    ValidationInfo,
)
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource
from sqlalchemy.engine import URL

_ENV_FILE_UNSET = object()
_PLACEHOLDERS = {
    "postgres",
    "password",
    "admin",
    "secret",
    "changeme",
    "change-me",
    "change-me-in-production",
    "change-me-in-production-use-openssl-rand-hex-32",
    "your-api-key",
    "your-api-key-here",
    "replace-me",
    "replace-with-a-secure-value",
}


class ConfigurationError(RuntimeError):
    """Only fixed codes/schema field names may cross the bootstrap boundary."""


def _credential_is_invalid(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized in _PLACEHOLDERS
        or normalized.startswith(("change-me", "replace-", "your-"))
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _host(value: str) -> str:
    """Validate a bare hostname/IP and bracket IPv6 for URL construction."""
    bare = value.removeprefix("[").removesuffix("]")
    try:
        address = ipaddress.ip_address(bare)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?", value):
            raise ValueError("CONNECTION_HOST_INVALID") from None
        return value
    return f"[{address}]" if address.version == 6 else str(address)


def _validate_endpoint(value: str) -> None:
    try:
        parsed = urlsplit(value)
        if (
            value != value.strip()
            or any(char.isspace() for char in value)
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        _host(parsed.hostname)
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("PROVIDER_ENDPOINT_INVALID") from None


def find_env_file() -> Path | None:
    """Find .env file in current or parent directories."""
    current = Path.cwd()
    for path in [current, current.parent]:
        env_file = path / ".env"
        if env_file.exists():
            return env_file
    return None


class MCPStdioServerSettings(BaseModel):
    """Configuration for one application-managed stdio MCP server."""

    namespace: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    def __init__(self, _env_file: Any = _ENV_FILE_UNSET, **values: Any) -> None:
        # Resolve per construction, never discover a dotenv at module definition time.
        environment = {
            key.upper(): value
            for key, value in os.environ.items()
            if key.upper() in {"ENVIRONMENT", "AGENTFORGE_ENV_FILE"}
        }
        selector = environment.get("AGENTFORGE_ENV_FILE")
        explicit_file = _env_file is not _ENV_FILE_UNSET
        selected_production = not explicit_file and selector is not None and selector != "none"
        production = (
            values.get("ENVIRONMENT") == "production"
            or environment.get("ENVIRONMENT") == "production"
            or selected_production
        )
        if production:
            if values.get("ENVIRONMENT", "production") != "production":
                raise ConfigurationError("ENVIRONMENT: PRODUCTION_DOWNGRADE_FORBIDDEN")
            if selected_production and environment.get("ENVIRONMENT", "production") != "production":
                raise ConfigurationError("ENVIRONMENT: PRODUCTION_DOWNGRADE_FORBIDDEN")
            values["ENVIRONMENT"] = "production"
        if not explicit_file:
            if selected_production:
                if not selector or not selector.strip() or not Path(selector).is_file():
                    raise ConfigurationError("CONFIGURATION_FILE_UNAVAILABLE")
                _env_file = selector
            elif selector == "none" or production:
                _env_file = None
            else:
                _env_file = find_env_file()
        if production and _env_file is not None and Path(_env_file).name == ".env":
            raise ConfigurationError("DEVELOPMENT_ENV_FILE_FORBIDDEN")
        # Empty production input must win over lower-priority/default values;
        # retain the existing empty-value convenience for local/test settings.
        values["_env_ignore_empty"] = not production
        super().__init__(_env_file=_env_file, **values)
        if self.ENVIRONMENT == "production" and not (production or explicit_file):
            raise ConfigurationError("DEVELOPMENT_ENV_FILE_FORBIDDEN")
        if production and self.ENVIRONMENT != "production":
            raise ConfigurationError("ENVIRONMENT: PRODUCTION_DOWNGRADE_FORBIDDEN")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Production credentials are literal, including ${...}. Keep standard
        # Pydantic decoding/precedence; disable only dotenv variable expansion.
        if (
            getattr(init_settings, "init_kwargs", {}).get("ENVIRONMENT") == "production"
            and isinstance(dotenv_settings, DotEnvSettingsSource)
            and dotenv_settings.env_file is not None
        ):
            file_path = dotenv_settings.env_file
            if not isinstance(file_path, (str, Path)):
                raise ConfigurationError("CONFIGURATION_SINGLE_FILE_REQUIRED")
            dotenv_settings.env_vars = {
                key if dotenv_settings.case_sensitive else key.lower(): value
                for key, value in dotenv_values(
                    file_path, encoding="utf-8", interpolate=False
                ).items()
                if value is not None
            }
        return init_settings, env_settings, dotenv_settings, file_secret_settings

    PROJECT_NAME: str = "agentforge"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False
    DB_ECHO: bool = (
        False  # Set DB_ECHO=true to log SQL queries (latency + log-noise drain by default)
    )
    ENVIRONMENT: Literal["development", "local", "staging", "production"] = "local"
    TIMEZONE: str = "UTC"  # IANA timezone (e.g. "UTC", "Europe/Warsaw", "America/New_York")
    MODELS_CACHE_DIR: Path = Path("./models_cache")
    MEDIA_DIR: Path = Path("./media")
    MAX_UPLOAD_SIZE_MB: int = 50  # Max file upload size in MB
    # Soft per-org storage cap surfaced on /billing — not enforced yet (5 GB).
    STORAGE_SOFT_LIMIT_BYTES: int = 5 * 1024 * 1024 * 1024

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = Field(default=5432, ge=1, le=65535)
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "agentforge"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """Build async PostgreSQL connection URL."""
        return self._database_url("postgresql+asyncpg")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Build sync PostgreSQL connection URL (for Alembic)."""
        return self._database_url("postgresql")

    def _database_url(self, driver: str) -> str:
        return URL.create(
            driver,
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=_host(self.POSTGRES_HOST).strip("[]"),
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        ).render_as_string(hide_password=False)

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str, info: ValidationInfo) -> str:
        """Validate SECRET_KEY is secure in production."""
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        env = info.data.get("ENVIRONMENT", "local") if info.data else "local"
        if v == "change-me-in-production-use-openssl-rand-hex-32" and env == "production":
            raise ValueError(
                "SECRET_KEY must be changed in production! "
                "Generate a secure key with: openssl rand -hex 32"
            )
        return v

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minutes
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALGORITHM: str = "HS256"

    # Public URL of the frontend; used to build OAuth redirect targets and
    # Stripe checkout/portal return URLs. Always declared (not gated) because
    # the billing model_validator references it unconditionally.
    FRONTEND_URL: str = "http://localhost:3000"

    API_KEY: str = "change-me-in-production"
    API_KEY_HEADER: str = "X-API-Key"

    @field_validator("API_KEY")
    @classmethod
    def validate_api_key(cls, v: str, info: ValidationInfo) -> str:
        """Validate API_KEY is set in production."""
        env = info.data.get("ENVIRONMENT", "local") if info.data else "local"
        if v == "change-me-in-production" and env == "production":
            raise ValueError(
                "API_KEY must be changed in production! "
                "Generate a secure key with: openssl rand -hex 32"
            )
        return v

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = Field(default=6379, ge=1, le=65535)
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = Field(default=0, ge=0)
    FLOWER_USER: str = ""
    FLOWER_PASSWORD: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:
        """Build Redis connection URL."""
        auth = f":{quote(self.REDIS_PASSWORD, safe='')}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{_host(self.REDIS_HOST)}:{self.REDIS_PORT}/{self.REDIS_DB}"

    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_PERIOD: int = 60  # seconds

    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""
    WORKFLOW_BACKGROUND_LEASE_SECONDS: int = Field(default=900, gt=0)
    WORKFLOW_RECOVERY_SCAN_INTERVAL_SECONDS: int = Field(default=60, gt=0)
    WORKFLOW_RECOVERY_BATCH_SIZE: int = Field(default=100, gt=0)
    WORKFLOW_RECOVERY_REDISPATCH_DELAY_SECONDS: int = Field(default=60, gt=0)
    KNOWLEDGE_INDEX_LEASE_SECONDS: int = Field(default=900, gt=0)
    KNOWLEDGE_INDEX_RECOVERY_SCAN_INTERVAL_SECONDS: int = Field(default=60, gt=0)
    KNOWLEDGE_INDEX_RECOVERY_BATCH_SIZE: int = Field(default=100, gt=0)
    KNOWLEDGE_INDEX_RECOVERY_REDISPATCH_DELAY_SECONDS: int = Field(default=60, gt=0)
    KNOWLEDGE_CHUNK_SIZE: int = Field(default=1000, gt=0)
    KNOWLEDGE_CHUNK_OVERLAP: int = Field(default=150, ge=0)
    KNOWLEDGE_MAX_CHUNKS: int = Field(default=2500, gt=0)
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = Field(default=1536, gt=0)
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str | None = None
    EMBEDDING_BATCH_SIZE: int = Field(default=32, gt=0)
    EMBEDDING_REQUEST_TIMEOUT_SECONDS: float = Field(default=30, gt=0)
    EMBEDDING_MAX_RETRIES: int = Field(default=2, ge=0, le=5)
    KNOWLEDGE_RETRIEVAL_DB_TIMEOUT_MS: int = Field(default=5000, gt=0)
    KNOWLEDGE_AGENT_ENABLED: bool = False
    KNOWLEDGE_AGENT_TIMEOUT_SECONDS: float = Field(default=60, gt=0)
    KNOWLEDGE_AGENT_MAX_TOOL_CALLS: int = Field(default=2, ge=1, le=2)
    # Legacy template-chat compatibility. Platform Runtime uses LLM_* settings below.
    OPENAI_API_KEY: str = ""
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str | None = None
    AI_MODEL: str = "gpt-5.5"
    AI_TEMPERATURE: float = 0.7
    AI_THINKING_ENABLED: bool = False
    AI_THINKING_EFFORT: str = "medium"  # "low", "medium", "high"
    AI_AVAILABLE_MODELS: list[str] = [
        "gpt-5.5",
        "gpt-5.5-pro",
        "gpt-5.4",
        "gpt-5.4-pro",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-5",
        "gpt-4.1",
    ]
    AI_FRAMEWORK: str = "langgraph"
    MCP_STDIO_SERVERS: list[MCPStdioServerSettings] = Field(default_factory=list)

    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
    ]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, v: list[str], info: ValidationInfo) -> list[str]:
        """Warn if CORS_ORIGINS is too permissive in production."""
        env = info.data.get("ENVIRONMENT", "local") if info.data else "local"
        if "*" in v and env == "production":
            raise ValueError(
                "CORS_ORIGINS cannot contain '*' in production! Specify explicit allowed origins."
            )
        return v

    @model_validator(mode="after")
    def validate_production_contract(self) -> Self:
        if self.ENVIRONMENT == "production":
            required = (
                "SECRET_KEY",
                "API_KEY",
                "POSTGRES_PASSWORD",
                "REDIS_PASSWORD",
                "POSTGRES_HOST",
                "POSTGRES_PORT",
                "POSTGRES_USER",
                "POSTGRES_DB",
                "REDIS_HOST",
                "REDIS_PORT",
                "REDIS_DB",
                "FLOWER_USER",
                "FLOWER_PASSWORD",
                "CORS_ORIGINS",
                "DEBUG",
                "DB_ECHO",
            )
            for name in required:
                value = getattr(self, name)
                if (
                    name not in self.model_fields_set
                    or value is None
                    or (isinstance(value, str) and not value.strip())
                ):
                    raise ValueError(f"{name}: PRODUCTION_VALUE_REQUIRED")
            for name in (
                "SECRET_KEY",
                "API_KEY",
                "POSTGRES_PASSWORD",
                "REDIS_PASSWORD",
                "FLOWER_PASSWORD",
            ):
                if _credential_is_invalid(getattr(self, name)):
                    raise ValueError(f"{name}: PRODUCTION_CREDENTIAL_INVALID")
            if self.DEBUG or self.DB_ECHO:
                raise ValueError("DEBUG_DB_ECHO_MUST_BE_FALSE")
            if not self.CORS_ORIGINS or "*" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS: EXPLICIT_ORIGINS_REQUIRED")
            # Flower uses comma-separated user:password entries. Reject ambiguity.
            if any(
                char in ":," or char.isspace() or ord(char) < 32 or ord(char) == 127
                for char in self.FLOWER_USER
            ) or any(char in self.FLOWER_PASSWORD for char in ":,"):
                raise ValueError("FLOWER_CREDENTIAL_FORMAT_INVALID")
            for name in ("POSTGRES_HOST", "REDIS_HOST"):
                _host(getattr(self, name))
            for key, model, endpoint in (
                ("LLM_API_KEY", "AI_MODEL", "LLM_BASE_URL"),
                ("EMBEDDING_API_KEY", "EMBEDDING_MODEL", "EMBEDDING_BASE_URL"),
            ):
                credential = getattr(self, key)
                if credential and _credential_is_invalid(credential):
                    raise ValueError(f"{key}: PROVIDER_CREDENTIAL_INVALID")
                if credential and not getattr(self, model).strip():
                    raise ValueError(f"{model}: PROVIDER_MODEL_REQUIRED")
                if getattr(self, endpoint):
                    _validate_endpoint(getattr(self, endpoint))
            if self.LLM_API_KEY and not self.LLM_PROVIDER.strip():
                raise ValueError("LLM_PROVIDER: PROVIDER_ID_REQUIRED")
            if self.OPENAI_API_KEY and _credential_is_invalid(self.OPENAI_API_KEY):
                raise ValueError("OPENAI_API_KEY: PROVIDER_CREDENTIAL_INVALID")
            if self.KNOWLEDGE_AGENT_ENABLED and not (self.LLM_API_KEY and self.EMBEDDING_API_KEY):
                raise ValueError("KNOWLEDGE_AGENT_PROVIDER_CONFIGURATION_REQUIRED")
            if self.EMBEDDING_DIMENSIONS != 1536:
                raise ValueError("EMBEDDING_DIMENSIONS_INCOMPATIBLE")
        canonical = self.REDIS_URL
        for name in ("CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
            current = getattr(self, name)
            if (
                self.ENVIRONMENT == "production"
                and name in self.model_fields_set
                and current != canonical
            ):
                raise ValueError(f"{name}: PRODUCTION_REDIS_OVERRIDE_UNSUPPORTED")
            if not current:
                setattr(self, name, canonical)
        return self


def load_settings(**values: Any) -> Settings:
    """Bootstrap boundary shared by API, Celery, workers and Alembic imports.

    Never stringify a source exception, its inputs, nested locations or chain.
    Direct Settings construction retains Pydantic's programmatic test interface.
    """
    try:
        return Settings(**values)
    except ValidationError as error:
        fields = sorted(
            {
                str(item["loc"][0])
                for item in error.errors(include_input=False)
                if item["loc"] and item["loc"][0] in Settings.model_fields
            }
        )
        diagnostic = "CONFIGURATION_INVALID" + (": " + ",".join(fields) if fields else "")
    except Exception:
        diagnostic = "CONFIGURATION_SOURCE_INVALID"
    # Raise outside the handler: no raw exception context retained on this error.
    raise ConfigurationError(diagnostic) from None


settings = load_settings()
