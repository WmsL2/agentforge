.PHONY: install format lint test test-cov run run-prod routes clean help \
	db-init db-migrate db-upgrade db-downgrade db-current db-history \
	dev dev-down dev-logs dev-rebuild dev-restart-workers frontend-dev \
	docker-clean seed bootstrap quickstart \
	prod prod-down prod-logs \
	upgrade upgrade-dry-run upgrade-new-features upgrade-finalize \
	create-admin user-create user-list \
	celery-worker celery-beat celery-flower \
	docker-up docker-down docker-logs docker-build docker-shell \
	docker-frontend docker-frontend-down docker-frontend-logs docker-frontend-build \
	docker-prod docker-prod-down docker-prod-logs docker-prod-build \
	docker-db docker-db-stop docker-redis docker-redis-stop \
	vercel-deploy

# === Development runtime ====================================================
#
# Day-to-day AgentForge development uses:
#
#   Docker:
#     - FastAPI backend
#     - PostgreSQL
#     - Redis
#     - Celery worker
#     - Celery beat
#     - Flower
#
#   Host:
#     - Next.js frontend via `bun run dev`
#
# docker-compose.yml is the single source of truth for the backend development
# stack. Backend application source is bind-mounted into the containers.
#
# The frontend Docker image is intentionally NOT used for normal development.
# docker-compose.frontend.yml exists only for production-image/container
# verification and must be rebuilt before each verification run.


# Wait for PostgreSQL to accept connections.
define _wait_for_db
	@echo "Waiting for PostgreSQL..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		if docker compose exec -T db pg_isready -U postgres >/dev/null 2>&1; then \
			echo "  ✅ DB ready"; exit 0; \
		fi; \
		printf '.'; sleep 2; \
	done; \
	echo "  ❌ DB not ready after 30s — check 'make dev-logs'"; exit 1
endef


# === Local development ======================================================

# Start the backend development stack and apply migrations.
#
# Backend app source is bind-mounted and Uvicorn reloads application changes.
# Celery processes do not auto-reload; use `make dev-restart-workers` after
# changing code executed by Celery.
#
# Rebuild the backend image with `make dev-rebuild` after changing Python
# dependencies, uv.lock, pyproject.toml, or backend/Dockerfile.
dev:
	@echo "▶ Starting AgentForge backend development stack..."
	@if ! docker compose up -d; then \
		echo ""; \
		echo "⚠ First start failed. Tearing down stale containers and retrying once..."; \
		echo "  Volumes are preserved; database data is safe."; \
		docker compose down --remove-orphans; \
		docker compose up -d; \
	fi
	$(call _wait_for_db)
	@echo "▶ Applying migrations..."
	docker compose exec -T app agentforge db upgrade
	@echo ""
	@echo "🚀 Backend development stack ready:"
	@echo "   API:        http://localhost:8000"
	@echo "   Docs:       http://localhost:8000/docs"
	@echo "   Flower:     http://localhost:5555"
	@echo "   PostgreSQL: localhost:5432"
	@echo "   Redis:      localhost:6379"
	@echo ""
	@echo "▶ Start the frontend in another terminal:"
	@echo "   make frontend-dev"
	@echo "   or: cd frontend && bun run dev"


# First-time setup from a fresh checkout.
bootstrap:
	@echo "▶ Building backend image..."
	docker compose build app
	$(MAKE) dev
	$(MAKE) seed


# One-shot local development admin seed.
seed:
	@echo "▶ Seeding admin user (admin@example.com / admin123)..."
	@if docker compose exec -T app \
		agentforge user list 2>/dev/null \
		| grep -q "admin@example.com"; then \
		echo "  (admin@example.com already exists — nothing to do)"; \
	else \
		docker compose exec -T app \
			agentforge user create \
				--email admin@example.com \
				--password admin123 \
				--superuser \
		&& echo "  ✅ Admin created"; \
	fi


# Legacy convenience alias.
quickstart: dev


# Run the Next.js development server on the host.
#
# This is the canonical frontend development mode.
frontend-dev:
	cd frontend && bun run dev


# Stop the backend development stack.
# Named volumes are preserved.
dev-down:
	docker compose down


# Tail backend development container logs.
dev-logs:
	docker compose logs -f


# Restart Celery processes after changing task/worker code.
#
# Source files are bind-mounted into the containers, but Celery does not
# automatically reload Python modules the way Uvicorn does.
dev-restart-workers:
	docker compose restart celery_worker celery_beat flower


# Force-rebuild the shared backend image and recreate processes using it.
#
# Use after changes to:
#   - backend/pyproject.toml
#   - backend/uv.lock
#   - backend/Dockerfile
#   - Python/system dependencies
dev-rebuild:
	docker compose build --no-cache app
	docker compose up -d --force-recreate app celery_worker celery_beat flower


# Full local development wipe.
# WARNING: destroys PostgreSQL, Redis, and uploaded-file volumes.
docker-clean:
	@echo "▶ Removing containers, networks, and development volumes..."
	@echo "  ⚠️  This deletes all local database data and uploaded files."
	docker compose down -v --remove-orphans
	@echo "✅ Development Docker state removed."


# === Production =============================================================

# Explicit identities are Make inputs, exported into Compose interpolation.
PROD_PROJECT ?=
RELEASE_ID ?=
PROD_ENV_FILE ?= backend/.env.prod
PROD_DOCKER ?= docker
export PROD_PROJECT RELEASE_ID PROD_ENV_FILE PROD_DOCKER
PROD_COMPOSE = "$$PROD_DOCKER" compose --project-name "$$PROD_PROJECT" --env-file "$$PROD_ENV_FILE" -f docker-compose.prod.yml

# POSIX shell + GNU Make; one serialized maintainer operation at a time.
# Never expand unvalidated identity values as shell source.
define _prod_context
set -eu; \
printf '%s' "$$PROD_PROJECT" | LC_ALL=C grep -Eq '^agentforge-prod-[a-z0-9][a-z0-9-]{0,39}$$' || { echo 'Invalid PROD_PROJECT (agentforge-prod-<lowercase-id> required)' >&2; exit 2; }; \
printf '%s' "$$RELEASE_ID" | LC_ALL=C grep -Eq '^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$$' || { echo 'Invalid RELEASE_ID' >&2; exit 2; }; \
case "$$(printf '%s' "$$RELEASE_ID" | tr '[:upper:]' '[:lower:]')" in dev|latest) echo 'Reserved RELEASE_ID' >&2; exit 2;; esac; \
base=$$(basename -- "$$PROD_ENV_FILE"); \
printf '%s' "$$base" | LC_ALL=C grep -Eq '^\.env\.prod(\.[A-Za-z0-9_-]+)*$$' || { echo 'Private production file name required' >&2; exit 2; }; \
case "$$base" in *.example|*.example.*) echo 'Public example is not production input' >&2; exit 2;; esac; \
test -f "$$PROD_ENV_FILE" && test -r "$$PROD_ENV_FILE" && test ! -L "$$PROD_ENV_FILE" || { echo 'Readable non-symlink production file required' >&2; exit 2; }; \
PROD_ENV_FILE="$$(cd -- "$$(dirname -- "$$PROD_ENV_FILE")" && pwd -P)/$$base"; \
if command -v cygpath >/dev/null 2>&1; then PROD_ENV_FILE=$$(cygpath -m "$$PROD_ENV_FILE"); fi; export PROD_ENV_FILE; \
version=$$("$$PROD_DOCKER" compose version --short); \
printf '%s' "$${version#v}" | awk -F. '{ if ($$1 !~ /^[0-9]+$$/ || $$2 !~ /^[0-9]+$$/ || $$3 !~ /^[0-9]+([+-].*)?$$/) exit 1; if ($$1>2 || ($$1==2 && ($$2>33 || ($$2==33 && $$3+0>=1)))) exit 0; exit 1; }' || { echo 'Docker Compose >= 2.33.1 required' >&2; exit 2; }; \
$(PROD_COMPOSE) config --quiet;
endef

prod:
	@$(_prod_context) \
	images=$$($(PROD_COMPOSE) config --images); \
	for image in $$images; do "$$PROD_DOCKER" image inspect -- "$$image" >/dev/null; done; \
	running=$$($(PROD_COMPOSE) ps --status running --quiet migrate); \
	test -z "$$running" || { echo 'Migration already running; serialize deployment' >&2; exit 2; }; \
	$(PROD_COMPOSE) run --rm --no-deps --pull never -T migrate python -c "from app.core.config import settings; print('CONFIGURATION_VALID')"; \
	$(PROD_COMPOSE) stop app celery_worker celery_beat flower frontend; \
	$(PROD_COMPOSE) rm --force migrate; \
	$(PROD_COMPOSE) up --detach --no-build --pull never

prod-down:
	@$(_prod_context) $(PROD_COMPOSE) down

prod-logs:
	@$(_prod_context) $(PROD_COMPOSE) logs -f


# === Setup ==================================================================

install:
	uv sync --directory backend --dev
	@if git rev-parse --git-dir > /dev/null 2>&1; then \
		uv run --directory backend pre-commit install; \
	else \
		echo "⚠️  Not a git repository - skipping pre-commit install"; \
		echo "   Run 'git init && make install' to set up pre-commit hooks"; \
	fi
	@echo ""
	@echo "✅ Installation complete!"
	@echo ""
	@echo "Recommended development workflow:"
	@echo "  • make dev           # Start Docker backend stack"
	@echo "  • make frontend-dev  # Start local Next.js dev server"


# === Template upgrade =======================================================

upgrade:
	uvx fastapi-fullstack@latest upgrade $(ARGS)


upgrade-dry-run:
	uvx fastapi-fullstack@latest upgrade --dry-run $(ARGS)


upgrade-new-features:
	uvx fastapi-fullstack@latest upgrade --with-new-features $(ARGS)


upgrade-finalize:
	uvx fastapi-fullstack@latest upgrade finalize $(ARGS)


# === Code quality ===========================================================

format:
	uv run --directory backend ruff format app tests cli
	uv run --directory backend ruff check app tests cli --fix


lint:
	uv run --directory backend ruff check app tests cli
	uv run --directory backend ruff format app tests cli --check
	uv run --directory backend ty check


# === Testing ================================================================

test:
	uv run --directory backend pytest tests/ -v


test-cov:
	uv run --directory backend pytest tests/ -v --cov=app --cov-report=html --cov-report=term-missing


# === Database ===============================================================

db-init: docker-db
	@echo "Waiting for PostgreSQL to be ready..."
	@sleep 8
	cd backend && uv run agentforge db migrate -m "initial" || true
	cd backend && uv run agentforge db upgrade
	@echo ""
	@echo "✅ Database initialized!"


db-migrate:
	@read -p "Migration message: " msg; \
	uv run --directory backend agentforge db migrate -m "$$msg"


db-upgrade:
	uv run --directory backend agentforge db upgrade


db-downgrade:
	uv run --directory backend agentforge db downgrade


db-current:
	uv run --directory backend agentforge db current


db-history:
	uv run --directory backend agentforge db history


# === Server =================================================================

run:
	uv run --directory backend agentforge server run --reload


run-prod:
	ENVIRONMENT=production AGENTFORGE_ENV_FILE="$(abspath backend/.env.prod)" uv run --directory backend agentforge server run --host 0.0.0.0 --port 8000


routes:
	uv run --directory backend agentforge server routes


# === Users ==================================================================

create-admin:
	@echo "Creating admin user..."
	uv run --directory backend agentforge user create-admin


user-create:
	uv run --directory backend agentforge user create


user-list:
	uv run --directory backend agentforge user list


# === Celery =================================================================

celery-worker:
	uv run --directory backend agentforge celery worker


celery-beat:
	uv run --directory backend agentforge celery beat


celery-flower:
	uv run --directory backend agentforge celery flower
	@echo ""
	@echo "✅ Flower started at http://localhost:5555"


# === Docker: backend development ============================================

# Compatibility alias for the canonical development stack.
docker-up: dev


docker-down:
	docker compose down
	docker compose -f docker-compose.frontend.yml down 2>/dev/null || true


docker-logs:
	docker compose logs -f


docker-build:
	docker compose build app


docker-shell:
	docker compose exec app /bin/bash


# === Docker: frontend image verification ====================================

# Build and run a fresh production-style frontend image.
#
# This is NOT the normal frontend development workflow.
# Stop `bun run dev` first because both modes use port 3000.
docker-frontend:
	@echo "▶ Building fresh frontend verification image..."
	@echo "  ⚠ Stop local 'bun run dev' first; port 3000 must be free."
	docker compose -f docker-compose.frontend.yml up -d --build --force-recreate frontend
	@echo ""
	@echo "✅ Frontend verification container started:"
	@echo "   http://localhost:3000"
	@echo ""
	@echo "Stop it after verification with:"
	@echo "   make docker-frontend-down"


docker-frontend-down:
	docker compose -f docker-compose.frontend.yml down


docker-frontend-logs:
	docker compose -f docker-compose.frontend.yml logs -f


docker-frontend-build:
	docker compose -f docker-compose.frontend.yml build frontend


# === Docker: production =====================================================

docker-prod: prod

docker-prod-down: prod-down

docker-prod-logs: prod-logs

docker-prod-build:
	@$(_prod_context) \
	$(PROD_COMPOSE) pull db redis; \
	$(PROD_COMPOSE) build --pull app frontend


# === Docker: individual services ===========================================

docker-db:
	docker compose up -d db
	@echo ""
	@echo "✅ PostgreSQL started on port 5432"
	@echo "   Connection: postgresql://postgres:postgres@localhost:5432/agentforge"


docker-db-stop:
	docker compose stop db


docker-redis:
	docker compose up -d redis
	@echo ""
	@echo "✅ Redis started on port 6379"


docker-redis-stop:
	docker compose stop redis


# === Vercel =================================================================

vercel-deploy:
	cd frontend && npx vercel --prod
	@echo ""
	@echo "✅ Frontend deployed to Vercel!"
	@echo "   Configure:"
	@echo "   BACKEND_URL=https://api.your-domain.com"
	@echo "   NEXT_PUBLIC_API_URL=https://api.your-domain.com"
	@echo "   NEXT_PUBLIC_WS_URL=wss://api.your-domain.com"
	@echo "   NEXT_PUBLIC_SITE_URL=https://your-domain.com"


# === Cleanup ================================================================

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ty_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml


# === Help ===================================================================

help:
	@echo ""
	@echo "AgentForge - Available Commands"
	@echo "======================================"
	@echo ""
	@echo "First-time setup:"
	@echo "  make bootstrap             Build backend + start stack + seed local admin"
	@echo ""
	@echo "Day-to-day development:"
	@echo "  make dev                   Start Docker backend stack + apply migrations"
	@echo "  make frontend-dev          Start local Next.js dev server on port 3000"
	@echo "  make dev-down              Stop Docker backend stack"
	@echo "  make dev-logs              Tail Docker backend logs"
	@echo "  make dev-restart-workers   Restart Celery worker / beat / Flower"
	@echo "  make dev-rebuild           Rebuild backend image after dependency changes"
	@echo ""
	@echo "Development state:"
	@echo "  make seed                  Seed local admin if missing"
	@echo "  make docker-clean          DESTROY local Docker volumes and database data"
	@echo ""
	@echo "Backend without Docker:"
	@echo "  make install               Install backend dependencies + pre-commit"
	@echo "  make run                   Run FastAPI locally with reload"
	@echo ""
	@echo "Code quality:"
	@echo "  make test                  Run backend tests"
	@echo "  make test-cov              Run backend tests with coverage"
	@echo "  make lint                  Run backend lint/type checks"
	@echo "  make format                Auto-format backend code"
	@echo ""
	@echo "Database:"
	@echo "  make db-migrate            Create a migration"
	@echo "  make db-upgrade            Apply migrations"
	@echo "  make db-downgrade          Roll back migration"
	@echo "  make db-current            Show current migration"
	@echo "  make db-history            Show migration history"
	@echo ""
	@echo "Users:"
	@echo "  make create-admin          Create admin user"
	@echo "  make user-create           Create user"
	@echo "  make user-list             List users"
	@echo ""
	@echo "Celery:"
	@echo "  make celery-worker         Run worker locally"
	@echo "  make celery-beat           Run beat locally"
	@echo "  make celery-flower         Run Flower locally"
	@echo ""
	@echo "Docker backend:"
	@echo "  make docker-up             Alias for make dev"
	@echo "  make docker-down           Stop backend + verification frontend containers"
	@echo "  make docker-logs           Tail backend logs"
	@echo "  make docker-build          Build backend image"
	@echo "  make docker-shell          Open backend container shell"
	@echo ""
	@echo "Frontend container verification:"
	@echo "  make docker-frontend       Rebuild + start fresh frontend image"
	@echo "  make docker-frontend-down  Stop verification frontend"
	@echo "  make docker-frontend-logs  Tail verification frontend logs"
	@echo "  make docker-frontend-build Build frontend image only"
	@echo ""
	@echo "Production:"
	@echo "  make prod                  Build/start production stack + migrate"
	@echo "  make prod-down             Stop production stack"
	@echo "  make prod-logs             Tail production logs"
	@echo ""
	@echo "Template upgrade:"
	@echo "  make upgrade-dry-run       Preview template update"
	@echo "  make upgrade               Apply template update"
	@echo "  make upgrade-new-features  Upgrade with newly added template features"
	@echo "  make upgrade-finalize      Finalize template upgrade"
	@echo ""
	@echo "Other:"
	@echo "  make routes                Show FastAPI routes"
	@echo "  make clean                 Clean local cache files"
	@echo ""