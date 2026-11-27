"""Compatible liveness, bounded critical readiness and protected local metrics."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.deps import ValidAPIKey
from app.core.config import settings
from app.schemas.base import HealthDetailResponse, HealthResponse
from app.services.health import (
    HealthSessionFactory,
    build_health_response,
    capability_checks,
    get_health_session_factory,
    probe_database,
    probe_redis,
)

router = APIRouter()


async def get_readiness_redis(request: Request) -> Any:
    """Missing lifespan state is an unavailable dependency, not an HTTP 500."""
    return getattr(request.state, "redis", None)


@router.get("/health", response_model=HealthResponse)
async def health_check() -> dict[str, Any]:
    return {"status": "healthy", "max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB}


@router.get("/health/live", response_model=HealthDetailResponse)
async def liveness_probe() -> dict[str, Any]:
    return build_health_response(
        status="alive", details={"version": __version__, "environment": settings.ENVIRONMENT}
    )


@router.get("/health/ready", response_model=None)
async def readiness_probe(
    factory: Annotated[HealthSessionFactory, Depends(get_health_session_factory)],
    redis: Annotated[Any, Depends(get_readiness_redis)],
) -> dict[str, Any] | JSONResponse:
    database, cache = await asyncio.gather(probe_database(factory), probe_redis(redis))
    checks = {"database": database, "redis": cache, **capability_checks()}
    ready = database["status"] == cache["status"] == "healthy"
    response = build_health_response(status="ready" if ready else "not_ready", checks=checks)
    response.update(checks)
    return response if ready else JSONResponse(status_code=503, content=response)


@router.get("/ready", response_model=None)
async def readiness_check(
    factory: Annotated[HealthSessionFactory, Depends(get_health_session_factory)],
    redis: Annotated[Any, Depends(get_readiness_redis)],
) -> dict[str, Any] | JSONResponse:
    return await readiness_probe(factory=factory, redis=redis)


@router.get("/metrics")
async def metrics(request: Request, _key: ValidAPIKey) -> JSONResponse:
    return JSONResponse(
        request.app.state.operational_metrics.snapshot(), headers={"Cache-Control": "no-store"}
    )
