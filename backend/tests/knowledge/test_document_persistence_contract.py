"""Static migration and ORM contract checks for Atomic 2."""

from pathlib import Path

from app.db.models.knowledge import KnowledgeDocument


def test_document_model_contains_private_storage_and_parse_contract() -> None:
    columns = KnowledgeDocument.__table__.columns
    assert set(columns.keys()) >= {
        "id",
        "workspace_id",
        "knowledge_base_id",
        "created_by_user_id",
        "filename",
        "mime_type",
        "size_bytes",
        "sha256",
        "storage_path",
        "parse_status",
        "parse_error_code",
        "parsed_content",
        "page_count",
        "parse_metadata",
        "created_at",
        "updated_at",
    }
    assert "knowledge_documents_storage_path_key" in {
        constraint.name for constraint in KnowledgeDocument.__table__.constraints
    }


def test_0044_migration_is_reversible_and_follows_0043() -> None:
    migration = (
        Path(__file__).parents[2] / "alembic" / "versions" / "0044_create_knowledge_documents.py"
    )
    namespace: dict[str, object] = {}
    exec(compile(migration.read_text(encoding="utf-8"), str(migration), "exec"), namespace)
    assert namespace["revision"] == "0044_create_knowledge_documents"
    assert namespace["down_revision"] == "0043_create_knowledge_bases"
    source = migration.read_text(encoding="utf-8")
    assert "knowledge_documents_workspace_knowledge_base_fkey" in source
    assert 'ondelete="CASCADE"' in source
    assert 'ondelete="SET NULL"' in source
    assert 'drop_table("knowledge_documents")' in source
