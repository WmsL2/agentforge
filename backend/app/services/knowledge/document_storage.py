"""Private, path-safe storage for knowledge documents."""

from __future__ import annotations

import asyncio
import os
import re
import stat
from pathlib import Path, PurePosixPath
from uuid import UUID

from app.core.exceptions import BadRequestError, InternalError

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


class KnowledgeDocumentStorage:
    def __init__(self, media_dir: Path):
        self._root = media_dir.resolve() / "knowledge"

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        name = Path(filename).name.strip()
        name = _SAFE_FILENAME.sub("_", name).strip(" .")
        if not name or name in {".", ".."}:
            raise BadRequestError(
                message="Invalid document filename", code="DOCUMENT_FILENAME_INVALID"
            )
        suffix = Path(name).suffix
        stem_limit = max(1, 255 - len(suffix))
        return f"{Path(name).stem[:stem_limit]}{suffix}" if len(name) > 255 else name

    def build_storage_path(
        self, *, workspace_id: UUID, knowledge_base_id: UUID, document_id: UUID, filename: str
    ) -> str:
        return PurePosixPath(
            str(workspace_id), str(knowledge_base_id), str(document_id), filename
        ).as_posix()

    async def save(self, relative_path: str, data: bytes) -> None:
        await asyncio.to_thread(self._save_sync, relative_path, data)

    async def delete(self, relative_path: str) -> None:
        await asyncio.to_thread(self._delete_sync, relative_path)

    async def resolve_for_download(self, relative_path: str) -> Path:
        return await asyncio.to_thread(self._resolve_existing, relative_path)

    async def reconcile_orphans(self, live_paths: set[str]) -> list[str]:
        """Return relative candidates for review. This operation never mutates storage."""
        return await asyncio.to_thread(self._preview_orphans, set(live_paths))

    def _safe_target(self, relative_path: str) -> Path:
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise InternalError(message="Unsafe document storage path")
        target = self._root.joinpath(*pure.parts)
        root = self._ensure_safe_root()
        current = root
        for part in pure.parts[:-1]:
            current = current / part
            if current.exists() and current.is_symlink():
                raise InternalError(message="Unsafe document storage path")
        resolved_parent = target.parent.resolve()
        if resolved_parent != root and root not in resolved_parent.parents:
            raise InternalError(message="Unsafe document storage path")
        return target

    def _ensure_safe_root(self) -> Path:
        root = self._root
        if root.is_symlink():
            raise InternalError(message="Unsafe document storage root")
        root.mkdir(parents=True, exist_ok=True)
        if root.resolve() != root:
            raise InternalError(message="Unsafe document storage root")
        return root

    def _save_sync(self, relative_path: str, data: bytes) -> None:
        target = self._safe_target(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with target.open("xb") as file_handle:
                created = True
                file_handle.write(data)
                file_handle.flush()
                os.fsync(file_handle.fileno())
        except Exception:
            if created and target.exists() and not target.is_symlink():
                target.unlink(missing_ok=True)
            raise

    def _delete_sync(self, relative_path: str) -> None:
        target = self._safe_target(relative_path)
        if target.is_symlink():
            raise InternalError(message="Unsafe document storage path")
        target.unlink(missing_ok=True)
        parent = target.parent
        while parent != self._root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def _resolve_existing(self, relative_path: str) -> Path:
        target = self._safe_target(relative_path)
        if target.is_symlink() or not target.is_file():
            raise InternalError(
                message="Document file is unavailable", code="DOCUMENT_FILE_UNAVAILABLE"
            )
        resolved = target.resolve(strict=True)
        if self._root not in resolved.parents:
            raise InternalError(message="Unsafe document storage path")
        return resolved

    def _preview_orphans(self, live_paths: set[str]) -> list[str]:
        root = self._root
        if root.is_symlink() or root.resolve() != root:
            raise InternalError(message="Unsafe document storage root")
        if not root.exists():
            return []
        if not root.is_dir():
            raise InternalError(message="Unsafe document storage root")
        normalized = {PurePosixPath(path).as_posix() for path in live_paths}
        candidates: list[str] = []
        directories = [root]
        while directories:
            directory = directories.pop()
            if directory.resolve() != directory or directory.is_symlink():
                continue
            for entry in directory.iterdir():
                try:
                    mode = entry.lstat().st_mode
                    if entry.is_symlink() or entry.resolve() != entry:
                        continue
                except FileNotFoundError:
                    # A writer may remove a file while a preview is in flight.
                    continue
                if stat.S_ISDIR(mode):
                    directories.append(entry)
                elif stat.S_ISREG(mode):
                    relative = entry.relative_to(root).as_posix()
                    if relative not in normalized:
                        candidates.append(relative)
        return sorted(candidates)
