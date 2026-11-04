"""Filesystem safety and orphan recovery tests."""

from pathlib import Path
from uuid import uuid4

import pytest

from app.core.exceptions import InternalError
from app.services.knowledge.document_storage import KnowledgeDocumentStorage


@pytest.mark.anyio
async def test_save_download_delete_and_duplicate_refusal(tmp_path: Path) -> None:
    storage = KnowledgeDocumentStorage(tmp_path)
    key = storage.build_storage_path(
        workspace_id=uuid4(), knowledge_base_id=uuid4(), document_id=uuid4(), filename="a.txt"
    )
    await storage.save(key, b"hello")
    path = await storage.resolve_for_download(key)
    assert path.read_bytes() == b"hello"
    with pytest.raises(FileExistsError):
        await storage.save(key, b"replace")
    assert path.read_bytes() == b"hello"
    await storage.delete(key)
    assert not path.exists()


@pytest.mark.anyio
async def test_traversal_and_symlink_escape_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = KnowledgeDocumentStorage(tmp_path)
    with pytest.raises(InternalError):
        await storage.save("../escape.txt", b"bad")
    root = tmp_path / "knowledge"
    root.mkdir()
    link = root / "link"
    link.mkdir()
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == link or original_is_symlink(path),
    )
    with pytest.raises(InternalError):
        await storage.save("link/escape.txt", b"bad")
    assert not (link / "escape.txt").exists()


@pytest.mark.anyio
async def test_reconciliation_removes_only_unreferenced_regular_files(tmp_path: Path) -> None:
    storage = KnowledgeDocumentStorage(tmp_path)
    live, orphan = "w/k/d/live.txt", "w/k/x/orphan.txt"
    await storage.save(live, b"live")
    await storage.save(orphan, b"orphan")
    assert await storage.reconcile_orphans({live}) == 1
    assert (await storage.resolve_for_download(live)).read_bytes() == b"live"


@pytest.mark.anyio
async def test_reconciliation_rejects_symlinked_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = KnowledgeDocumentStorage(tmp_path)
    root = tmp_path / "knowledge"
    root.mkdir()
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == root or original_is_symlink(path),
    )
    with pytest.raises(InternalError):
        await storage.reconcile_orphans(set())


def test_filename_is_basename_sanitized_and_bounded() -> None:
    assert KnowledgeDocumentStorage.sanitize_filename("../../evil name?.txt") == "evil name_.txt"
    assert len(KnowledgeDocumentStorage.sanitize_filename("x" * 300 + ".txt")) <= 255
