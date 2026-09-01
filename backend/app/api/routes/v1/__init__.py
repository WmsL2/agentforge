"""API v1 router aggregation."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from fastapi import APIRouter

from app.api.routes.v1 import health
from app.api.routes.v1 import admin_users, auth, users
from app.api.routes.v1 import sessions
from app.api.routes.v1 import conversations
from app.api.routes.v1 import admin_conversations
from app.api.routes.v1 import agent
from app.api.routes.v1 import files
from app.api.routes.v1 import admin_stats
from app.api.routes.v1 import workflow

v1_router = APIRouter()

v1_router.include_router(health.router, tags=["health"])

v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])
v1_router.include_router(users.router, prefix="/users", tags=["users"])

v1_router.include_router(
    sessions.router,
    prefix="/sessions",
    tags=["sessions"],
)

v1_router.include_router(
    conversations.router,
    prefix="/conversations",
    tags=["conversations"],
)

v1_router.include_router(agent.router, tags=["agent"])

v1_router.include_router(files.router, tags=["files"])
v1_router.include_router(workflow.router, prefix="/workflows", tags=["workflows"])

v1_router.include_router(
    admin_conversations.router,
    prefix="/admin/conversations",
    tags=["admin-conversations"],
)

v1_router.include_router(
    admin_users.router,
    prefix="/admin/users",
    tags=["admin:users"],
)

v1_router.include_router(
    admin_stats.router,
    prefix="/admin",
    tags=["admin:stats"],
)
