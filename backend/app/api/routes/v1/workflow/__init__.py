"""Combined workflow definition and run router."""

from fastapi import APIRouter

from app.api.routes.v1.workflow.definition import router as definition_router
from app.api.routes.v1.workflow.run import router as run_router

router = APIRouter()
router.include_router(definition_router, prefix="/workflows")
router.include_router(run_router, prefix="/workflows")
