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
from app.api.routes.v1 import workspaces
from app.api.routes.v1 import knowledge
from app.api.routes.v1 import knowledge_documents
from app.api.routes.v1 import knowledge_search

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
v1_router.include_router(workflow.router, tags=["workflows"])
v1_router.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
v1_router.include_router(
    knowledge.router,
    prefix="/workspaces/{workspace_id}/knowledge-bases",
    tags=["knowledge-bases"],
)
v1_router.include_router(
    knowledge_documents.router,
    prefix="/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/documents",
    tags=["knowledge-documents"],
)
v1_router.include_router(
    knowledge_search.router,
    prefix="/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/search",
    tags=["knowledge-search"],
)

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
