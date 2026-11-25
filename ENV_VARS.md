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

All production Make targets use `--env-file backend/.env.prod`. Backend role
service env_file inputs also use that file. Compose shell variables override
interpolation-file values; a shared environment mapping explicitly supplies the
same resolved DB/Redis/auth/Flower/CORS values to every backend role, and the
same DB/Redis values to infrastructure. This prevents service env_file precedence
from splitting credentials. Do not use bare Compose production commands that
omit the explicit interpolation file. API, Worker, Beat and Flower force
production, debug false, DB echo false and no dotenv discovery. Migration via
API exec inherits that contract. Redis command/password arguments use YAML
lists, not a shell-split command. This is static implementation, not runtime
production authentication proof. Image identity, migration gating, network
isolation/egress and TLS remain later Atomics.

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
