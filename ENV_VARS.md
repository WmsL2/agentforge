# Environment variables

The authoritative model is `backend/app/core/config.py`. Public templates are
`backend/.env.example` (development) and `backend/.env.prod.example` (production).
Private `.env` and `.env.prod` files must never be committed, printed or copied
into images. No actual production file is generated automatically.

## Source selection and precedence

Development discovers `.env` in the current directory, then its parent.
Production never implicitly discovers or falls back to that development file.
Set `ENVIRONMENT=production` for environment-only production loading, or set
`AGENTFORGE_ENV_FILE` to an explicit private production file path. A selected
file forces production mode; a conflicting process/constructor environment is
rejected. `AGENTFORGE_ENV_FILE=none` disables dotenv discovery for offline tests
and containers. An empty/missing selected production file fails safely.

`make run-prod` explicitly sets ENVIRONMENT=production and selects the absolute
backend/.env.prod path before invoking uv. That path remains valid when
`uv run --directory backend` changes the execution directory. Inherited local
mode is overridden; a missing production file fails closed without falling back
to development configuration. Normal `make run` remains the development entry.

Precedence: explicit constructor fields > process environment > selected dotenv
> model defaults. Production mode is locked against downgrade. Explicit
`Settings(_env_file=None, ...)` bypasses file selection/discovery but still reads
process inputs; isolate the process environment when testing. Empty production
values are preserved for validation, not skipped in favor of defaults.
Production dotenv values are literal (no `${...}` expansion). For Compose,
single-quote private dotenv secrets so `$`, `#` and spaces are literal. Never
pre-percent-encode credentials. No credentials are trimmed or normalized.

## Connection inputs and derived URLs

| Input | Local default | Production contract |
| --- | --- | --- |
| `ENVIRONMENT` | local | production; development/local/staging/production are the only values |
| `DEBUG`, `DB_ECHO` | false | explicitly false |
| `POSTGRES_HOST`, `POSTGRES_PORT` | localhost, 5432 | explicit host/port; Compose uses db and configured port |
| `POSTGRES_USER`, `POSTGRES_DB` | postgres, agentforge | explicit nonblank values |
| `POSTGRES_PASSWORD` | empty | explicit non-placeholder secret |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | localhost, 6379, 0 | explicit values; DB >= 0; port 1–65535 |
| `REDIS_PASSWORD` | absent | explicit non-placeholder secret |
| `SECRET_KEY` | insecure development placeholder | explicit non-placeholder, at least 32 characters |
| `API_KEY` | insecure development placeholder | explicit non-placeholder secret |
| `FLOWER_USER`, `FLOWER_PASSWORD` | empty | explicit user and non-placeholder password |
| `CORS_ORIGINS` | localhost origins | explicit nonempty list, no wildcard |

`DATABASE_URL` and `DATABASE_URL_SYNC` are computed strings from PostgreSQL
inputs; `REDIS_URL` is computed from Redis inputs. They are not full-URL input
fields. SQLAlchemy constructs DB URLs and percent encoding protects Redis
credentials. Bare/bracketed IPv6 is supported. Reserved characters, Unicode,
spaces and literal percent sequences remain part of the original credential.

Production POSTGRES_DB must survive both async and sync SQLAlchemy string-URL
parsers exactly, with no query parameters. Question marks (including a trailing
`?` or query-like `?sslmode=...`) are deliberately unsupported database-name
syntax and rejected. Names with hyphens, underscores, dots, spaces, Unicode,
slashes, hash, percent or @ remain supported when they round-trip unchanged.
No SQL identifier rewriting or credential-encoding change is performed.

`CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` default to computed REDIS_URL.
Local/development/test may explicitly override them, including CI Redis DB 15.
Supported production accepts only omission or exact equality to the canonical
Redis-derived URL. Empty, unauthenticated, different-host/DB and other-scheme
production overrides are rejected. Do not put these overrides in `.env.prod`.

## Production credential policy

Missing, empty, whitespace-only, control-character and known placeholder secrets
are rejected. Known placeholders include postgres/password/admin/secret,
changeme/change-me, the existing JWT/API defaults, and change-me*, replace-*,
your-* example prefixes (case-insensitive, comparison only). Legitimate secret
values are preserved exactly, including leading/trailing spaces when not blank.
Only SECRET_KEY has a general minimum length (32); operators must generate
strong unique random values for all secrets. This policy is not an entropy test.

Flower uses comma-separated user:password entries. This supported single-account
contract rejects colon/comma in either component and whitespace in the username;
password controls are also rejected. A username such as admin is not itself a
secret or proof of an insecure password. Production requires both fields.

## Provider capabilities

| Field | Responsibility |
| --- | --- |
| `LLM_API_KEY`, `LLM_PROVIDER`, `AI_MODEL`, `LLM_BASE_URL` | Platform Runtime, OpenAI-compatible protocol; provider name is metadata |
| `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_BASE_URL` | Knowledge indexing and retrieval |
| `EMBEDDING_DIMENSIONS` | Production storage contract: exactly 1536 |
| `OPENAI_API_KEY` | Legacy template chat only; never a Platform Runtime fallback |
| `KNOWLEDGE_AGENT_ENABLED` | Existing dedicated Knowledge Agent flag; default false |

Empty optional keys mean that capability is unavailable, not operational. Basic
deterministic workflows need no Provider credential. In production, configured
keys cannot be whitespace/placeholders; corresponding model/provider identities
must be nonblank. Explicit endpoints must be syntactically valid HTTP(S) URLs
with a host and valid optional port, without credentials/query/fragment/whitespace.
Empty endpoints retain SDK defaults. Knowledge Agent enabled in production
requires both LLM and Embedding keys/configuration. Full-platform staging also
requires both. Positive timeout/batch/chunk/lease checks remain in Settings.
Configuration validity never proves connectivity, availability or answer quality.

## Production Compose contract

Production operations require PROD_PROJECT (agentforge-prod-<lowercase-id>),
RELEASE_ID (explicit release identifier, never dev/latest), and PROD_ENV_FILE
(default backend/.env.prod; private .env.prod.<id> variants supported). Every
Make path validates the identity/file, requires Compose >=2.33.1 and uses explicit
project selection plus the same absolute file for interpolation and backend
service env_file. Shared mappings preserve identical infra/backend credentials.
API, Worker, Beat, Flower and one-shot migrate enforce production and no dotenv
discovery. migrate runs alembic upgrade head; API exec migration is no longer the
deployment mechanism. All business roles require successful migrate completion.

PYTHON_IMAGE/UV_IMAGE/BUN_IMAGE and POSTGRES_IMAGE/REDIS_IMAGE require explicit
compatible refs; prefer verified immutable digests. docker-prod-build prepares
infra and builds backend once/frontend; prod only selects/verifies local images,
checks Settings in a disposable no-deps/no-pull migrate-image container before it
stops scoped business roles, removes old stopped migrate and starts with no build
or pull. docker-prod aliases the same gate. No stale gate reuse, sleep, automatic
recovery restart, volume deletion or implicit old-volume adoption. See
[deployment guide](docs/deploy.md) for full constraints and commands.

Application references are agentforge/<project>-backend:<release> and
agentforge/<project>-frontend:<release>; repository/tag separation prevents
ambiguous project/release concatenation. Preflight uses the same selected file,
release and five-role production contract, without migrations/media/connections.
Failure prevents business stop/rm/up. It may create project networks; temporary
container removal does not imply network cleanup. Volumes/networks are project
scoped. Only API/Worker have the extra provider-egress network/default gateway;
DB/Redis remain internal without published ports. API/Frontend/Flower host bindings
are explicit API_BIND_HOST/API_HOST_PORT etc., default loopback. Browser public
build args are separate from private runtime fields; COOKIE_SECURE remains true.
Bridge topology is not an egress firewall. Actual deployment/provider/persistence
verification is NOT RUN; health is A4, recovery A5, TLS/proxy A6, staging A7.

## Safe validation

For a preconfigured environment-only production process, set ENVIRONMENT to
production before starting it. For an explicit file, set AGENTFORGE_ENV_FILE to
its private path first. Then, from backend with existing dependencies:

```bash
python -c "from app.core.config import settings; print('CONFIGURATION_VALID')"
```

This imports only the shared configuration module: no DB/Redis connection or
Provider request. The bootstrap boundary emits CONFIGURATION_INVALID (optionally
schema field names) or CONFIGURATION_SOURCE_INVALID and suppresses underlying
exception values/chains. Never print Settings, validation errors with inputs,
computed URLs, dotenv contents or `docker compose config` output against secrets.
Direct Settings construction remains Pydantic's programmatic validation interface;
bootstrap/operational code must use the global settings or load_settings boundary.

## Other existing settings

Project/timezone/media/upload, token expiry, pool sizing, MCP stdio, bounded
recovery/indexing, rate-limit and frontend settings remain supported. See
`docs/configuration.md` for details. Frontend BACKEND_URL is server-only;
NEXT_PUBLIC_* are public build-time values and never carry secrets. Secure,
HttpOnly cookies and their explicit COOKIE_SECURE policy remain unchanged.
