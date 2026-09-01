"""Combined workflow definition and run router."""

from app.api.routes.v1.workflow.definition import router as definition_router
from app.api.routes.v1.workflow.run import router as run_router

router = definition_router
router.include_router(run_router)
