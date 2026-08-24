"""MCP connections migration — skipped because MCP client is disabled.

Revision ID: 0026_create_mcp_connections
Revises: 0025

No-op placeholder that preserves the Alembic revision chain when the
template MCP client feature is disabled.
"""

revision = "0026_create_mcp_connections"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
