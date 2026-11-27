"""Static contracts and GNU Make command flow; never invoke real Docker."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROLES = ("app", "celery_worker", "celery_beat", "flower", "migrate")
BUSINESS = ("app", "celery_worker", "celery_beat", "flower", "frontend")


@pytest.fixture
def compose():
    return yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))


def test_shared_release_artifacts(compose):
    services = compose["services"]
    image = services["app"]["image"]
    assert "${PROD_PROJECT:?" in image and "${RELEASE_ID:?" in image
    for role in BACKEND_ROLES:
        assert services[role]["image"] == image
        assert services[role]["pull_policy"] == "never"
        assert ("build" in services[role]) == (role == "app")
    assert "${PROD_PROJECT:?" in services["frontend"]["image"]
    assert "${RELEASE_ID:?" in services["frontend"]["image"]
    assert services["frontend"]["pull_policy"] == "never"
    assert "agentforge_backend:dev" not in str(compose)
    assert set(services["app"]["build"]["args"]) == {"PYTHON_IMAGE", "UV_IMAGE"}
    assert "${BUN_IMAGE:?" in services["frontend"]["build"]["args"]["BUN_IMAGE"]
    for role in ("db", "redis"):
        assert ":?" in services[role]["image"]


@pytest.mark.parametrize("role", ["app", "frontend"])
def test_repository_and_tag_partition_prevents_cross_project_collision(compose, role):
    pairs = [("agentforge-prod-a", "b-r1"), ("agentforge-prod-a-b", "r1")]
    # Reproduce the ambiguity of the previously accepted inputs.
    assert len({f"{project}-{release}" for project, release in pairs}) == 1
    template = compose["services"][role]["image"]
    references = [
        template.replace("${PROD_PROJECT:?PROD_PROJECT is required}", project).replace(
            "${RELEASE_ID:?RELEASE_ID is required}", release
        )
        for project, release in pairs
    ]
    suffix = "backend" if role == "app" else "frontend"
    assert references == [f"agentforge/{project}-{suffix}:{release}" for project, release in pairs]
    assert references[0] != references[1]
    assert references[0].split(":")[0] != references[1].split(":")[0]


def test_frozen_nonroot_multistage_builds_remain():
    backend = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
    assert "ARG PYTHON_IMAGE=python:3.12-slim" in backend
    assert "ARG UV_IMAGE=ghcr.io/astral-sh/uv:latest" in backend
    assert "FROM ${UV_IMAGE} AS uv_binary" in backend
    assert backend.count("FROM ${PYTHON_IMAGE}") == 2
    assert "uv sync --frozen --no-install-project --no-dev" in backend
    assert "uv sync --frozen --no-dev" in backend and "USER appuser" in backend
    assert "ARG BUN_IMAGE=oven/bun:1" in frontend
    assert "bun install --frozen-lockfile" in frontend and "USER nextjs" in frontend
    assert "FROM base AS runner" in frontend


def test_migration_success_is_required_for_every_business_role(compose):
    services = compose["services"]
    migrate = services["migrate"]
    assert migrate["command"] == ["alembic", "upgrade", "head"]
    assert migrate["restart"] == "no"
    assert migrate["depends_on"]["db"]["condition"] == "service_healthy"
    for role in BUSINESS:
        assert services[role]["depends_on"]["migrate"]["condition"] == (
            "service_completed_successfully"
        )
    for role in ("migrate", "celery_beat"):
        assert services[role]["healthcheck"] == {"disable": True}
    assert "healthcheck" not in services["app"]  # Inherits status-aware image probe.
    for role, probe in [("celery_worker", "worker"), ("flower", "flower")]:
        check = services[role]["healthcheck"]
        assert check["test"] == ["CMD", "python", "-m", "app.services.operational_probe", probe]
        assert check["timeout"] == "10s" and check["interval"] == "30s"
    front = services["frontend"]["healthcheck"]
    assert front["test"][:3] == ["CMD", "bun", "-e"]
    assert "AbortSignal.timeout(5000)" in front["test"][3] and "r.ok" in front["test"][3]
    assert front["timeout"] == "10s"
    backend = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    assert "CMD python -m app.services.operational_probe api" in backend
    assert "--timeout=10s" in backend


def test_authenticated_infrastructure_probes(compose):
    services = compose["services"]
    postgres = services["db"]["healthcheck"]["test"]
    assert postgres[:2] == ["CMD", "pg_isready"]
    assert postgres[postgres.index("-h") + 1] == "127.0.0.1"
    assert postgres[postgres.index("-d") + 1] == services["db"]["environment"]["POSTGRES_DB"]
    redis = services["redis"]
    assert (
        redis["environment"]["REDIS_PASSWORD"]
        == compose["x-production-environment"]["REDIS_PASSWORD"]
    )
    probe = redis["healthcheck"]["test"]
    assert probe[0] == "CMD-SHELL"
    assert 'REDISCLI_AUTH="$$REDIS_PASSWORD"' in probe[1]
    assert '&& [ "$$reply" = "PONG" ]' in probe[1]
    assert '"$$REDIS_PORT"' in probe[1]
    assert "echo" not in probe[1] and " -a " not in probe[1]


def test_networks_storage_and_exposure(compose):
    assert compose["networks"] == {
        "backend-internal": {"driver": "bridge", "internal": True},
        "provider-egress": {"driver": "bridge", "internal": False},
    }
    assert compose["volumes"] == {"media_data": None, "postgres_data": None, "redis_data": None}
    for role, service in compose["services"].items():
        assert "container_name" not in service and "privileged" not in service
        expected = (
            {"backend-internal", "provider-egress"}
            if role in {"app", "celery_worker"}
            else {"backend-internal"}
        )
        assert set(service["networks"]) == expected
        if role in {"app", "celery_worker"}:
            assert service["networks"]["provider-egress"]["gw_priority"] == 1
        assert not any(mount.startswith((".", "/")) for mount in service.get("volumes", []))
    services = compose["services"]
    assert (
        services["app"]["volumes"]
        == services["celery_worker"]["volumes"]
        == ["media_data:/app/media"]
    )
    assert services["db"]["volumes"] == ["postgres_data:/var/lib/postgresql/data"]
    assert services["redis"]["volumes"] == ["redis_data:/data"]
    assert "ports" not in services["db"] and "ports" not in services["redis"]
    for role in ("app", "frontend", "flower"):
        assert "BIND_HOST:-127.0.0.1}" in services[role]["ports"][0]
        assert "HOST_PORT:-" in services[role]["ports"][0]
    frontend = services["frontend"]
    assert frontend["environment"]["BACKEND_URL"] == "http://app:8000"
    assert frontend["environment"]["COOKIE_SECURE"] == "${COOKIE_SECURE:-true}"
    assert not any("PASSWORD" in name or "KEY" in name for name in frontend["build"]["args"])


@pytest.fixture
def fake_deployment(tmp_path):
    make = shutil.which("make")
    if os.name == "nt":
        git = shutil.which("git")
        shell = Path(git).parent.parent / "bin/sh.exe" if git else None
    else:
        shell = Path(shutil.which("sh")) if shutil.which("sh") else None
    if not make or not shell or not shell.is_file():
        pytest.skip(
            "GNU Make/POSIX shell unavailable; executable flow NOT RUN (static checks remain)"
        )
    work = tmp_path / "isolated deployment with spaces"
    work.mkdir()
    private = work / ".env.prod.offline"
    private.write_text("# synthetic file: fake Docker never reads it\n", encoding="utf-8")
    log = work / "calls.log"
    mock = work / "fake-docker"
    mock.write_text(
        """#!/bin/sh
set -eu
printf '%s|' "$@" >> "$FAKE_LOG"
printf '\\n' >> "$FAKE_LOG"
case "$*" in
  'compose version --short') printf '%s\\n' "${FAKE_VERSION:-2.33.1}"; exit 0;;
esac
case "$*" in
  *"${FAKE_FAIL:-never-match-this-step}"*) exit 42;;
esac
case "$*" in
  *'config --images') printf '%s\\n' "agentforge/$PROD_PROJECT-backend:$RELEASE_ID" "agentforge/$PROD_PROJECT-frontend:$RELEASE_ID" 'synthetic-postgres' 'synthetic-redis';;
  *'ps --status running --quiet migrate') if [ "${FAKE_RUNNING:-0}" = 1 ]; then echo synthetic-running-migrate; fi;;
esac
""",
        encoding="utf-8",
        newline="\n",
    )
    mock.chmod(0o700)

    def run(
        target="prod", *, fail="never-match-this-step", version="2.33.1", running="0", **values
    ):
        log.unlink(missing_ok=True)
        env = dict(
            os.environ,
            FAKE_LOG=str(log),
            FAKE_FAIL=fail,
            FAKE_VERSION=version,
            FAKE_RUNNING=running,
        )
        inputs = {
            "PROD_PROJECT": "agentforge-prod-offline",
            "RELEASE_ID": "r1",
            "PROD_ENV_FILE": private.as_posix(),
            "PROD_DOCKER": mock.as_posix(),
            "SHELL": shell.as_posix(),
        } | values
        result = subprocess.run(
            [
                make,
                "--no-print-directory",
                "-f",
                str(ROOT / "Makefile"),
                target,
                *(f"{name}={value}" for name, value in inputs.items()),
            ],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        calls = (
            [line.rstrip("|").split("|") for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        return result, calls

    return run, private


@pytest.mark.parametrize("target", ["prod", "docker-prod"])
def test_executable_startup_sequence_uses_selected_images_and_fresh_gate(fake_deployment, target):
    run, private = fake_deployment
    result, calls = run(target)
    assert result.returncode == 0, result.stderr
    actions = [" ".join(call) for call in calls]
    stop = next(i for i, item in enumerate(actions) if " stop app " in item)
    remove = next(i for i, item in enumerate(actions) if " rm --force migrate" in item)
    up = next(i for i, item in enumerate(actions) if " up --detach --no-build --pull never" in item)
    preflight = next(i for i, call in enumerate(calls) if "run" in call)
    query = next(i for i, call in enumerate(calls) if "ps" in call)
    assert query < preflight < stop < remove < up
    assert all(i < preflight for i, call in enumerate(calls) if call[:2] == ["image", "inspect"])
    preflight_call = calls[preflight]
    assert preflight_call[preflight_call.index("run") :] == [
        "run",
        "--rm",
        "--no-deps",
        "--pull",
        "never",
        "-T",
        "migrate",
        "python",
        "-c",
        "from app.core.config import settings; print('CONFIGURATION_VALID')",
    ]
    assert "--build" not in preflight_call and "alembic" not in preflight_call
    assert any("image inspect" in item for item in actions[:stop])
    assert any("config --quiet" in item for item in actions[:stop])
    for call in calls:
        if call[:2] == ["compose", "version"] or call[:2] == ["image", "inspect"]:
            continue
        assert call[call.index("--project-name") + 1] == "agentforge-prod-offline"
        assert Path(call[call.index("--env-file") + 1]).resolve() == private.resolve()
    assert not any("--build" in call or "exec" in call or "sleep" in call for call in calls)


@pytest.mark.parametrize(
    "failure", ["config --quiet", "image inspect", " ps ", " run ", " stop ", " rm ", " up "]
)
def test_deployment_failure_propagates_without_followup(fake_deployment, failure):
    run, _ = fake_deployment
    result, calls = run(fail=failure)
    assert result.returncode != 0
    assert failure.strip() in " ".join(calls[-1])
    assert not any("restart" in call for call in calls)


@pytest.mark.parametrize("target", ["prod", "docker-prod"])
def test_failed_settings_preflight_cannot_stop_existing_business(fake_deployment, target):
    run, _ = fake_deployment
    result, calls = run(target, fail=" run ")
    assert result.returncode != 0
    assert "run" in calls[-1] and "migrate" in calls[-1]
    assert not any("stop" in call or "rm" in call or "up" in call for call in calls)


@pytest.mark.parametrize(
    "values",
    [
        {"PROD_PROJECT": ""},
        {"PROD_PROJECT": "agentforge"},
        {"PROD_PROJECT": "agentforge-prod-X"},
        {"PROD_PROJECT": "agentforge-prod-a;echo unsafe"},
        {"RELEASE_ID": ""},
        {"RELEASE_ID": "latest"},
        {"RELEASE_ID": "dev"},
        {"RELEASE_ID": "r/1"},
        {"PROD_ENV_FILE": "backend/.env"},
        {"PROD_ENV_FILE": "backend/.env.prod.example"},
        {"PROD_ENV_FILE": "backend/.env.prod.missing"},
    ],
)
def test_invalid_identity_or_input_rejected_before_docker(fake_deployment, values):
    run, _ = fake_deployment
    result, calls = run(**values)
    assert result.returncode != 0
    assert calls == []


@pytest.mark.parametrize("version", ["2.32.9", "2.33.0", "broken"])
def test_unsupported_compose_rejected_before_deployment_changes(fake_deployment, version):
    run, _ = fake_deployment
    result, calls = run(version=version)
    assert result.returncode != 0
    assert calls == [["compose", "version", "--short"]]


def test_running_migration_is_not_removed(fake_deployment):
    run, _ = fake_deployment
    result, calls = run(running="1")
    assert result.returncode != 0
    assert not any(
        "run" in call or "stop" in call or "rm" in call or "up" in call for call in calls
    )


def test_preflight_has_no_private_media_or_separate_settings_implementation(compose):
    migrate = compose["services"]["migrate"]
    assert "volumes" not in migrate
    assert migrate["environment"] == compose["x-production-environment"]
    assert migrate["environment"]["ENVIRONMENT"] == "production"
    assert migrate["image"] == compose["services"]["app"]["image"]
    assert "build" not in migrate and migrate["pull_policy"] == "never"
    flower = compose["services"]["flower"]["environment"]
    assert flower["FLOWER_BASIC_AUTH"] == (
        compose["x-production-environment"]["FLOWER_USER"]
        + ":"
        + compose["x-production-environment"]["FLOWER_PASSWORD"]
    )


def test_each_release_update_removes_previous_migration_gate(fake_deployment):
    run, _ = fake_deployment
    for release in ("r1", "r2"):
        result, calls = run(RELEASE_ID=release)
        assert result.returncode == 0, result.stderr
        assert any(call[-3:] == ["rm", "--force", "migrate"] for call in calls)
        assert any(
            f"agentforge/agentforge-prod-offline-backend:{release}" in call for call in calls
        )
        assert calls[-1][-5:] == ["up", "--detach", "--no-build", "--pull", "never"]


@pytest.mark.parametrize("failure", [" pull ", " build "])
def test_build_failure_stops_artifact_preparation(fake_deployment, failure):
    run, _ = fake_deployment
    result, calls = run("docker-prod-build", fail=failure)
    assert result.returncode != 0
    assert failure.strip() in calls[-1]
    assert not any("up" in call or "stop" in call for call in calls)


@pytest.mark.parametrize(
    "target",
    ["prod-down", "docker-prod-down", "prod-logs", "docker-prod-logs", "docker-prod-build"],
)
def test_stop_logs_and_build_targets_are_scoped_and_non_destructive(fake_deployment, target):
    run, _ = fake_deployment
    result, calls = run(target)
    assert result.returncode == 0, result.stderr
    assert not any("up" in call or "--volumes" in call or "-v" in call for call in calls)
    if target == "docker-prod-build":
        assert calls[-2][-3:] == ["pull", "db", "redis"]
        assert calls[-1][-4:] == ["build", "--pull", "app", "frontend"]
    else:
        assert calls[-1][-1:] == ["down"] if "down" in target else calls[-1][-2:] == ["logs", "-f"]
