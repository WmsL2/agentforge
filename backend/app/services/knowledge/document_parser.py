"""Bounded, synchronous document parsing primitives.

Callers must execute ``parse`` outside the event loop.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from docx import Document

from app.core.exceptions import BadRequestError

MAX_PDF_PAGES = 200
MAX_TEXT_CHARS = 2_000_000
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_ZIP_RATIO = 100

_MIME_BY_EXTENSION = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".markdown": {"text/markdown", "text/plain"},
}


@dataclass(frozen=True)
class ParsedDocument:
    status: str
    content: str | None
    error_code: str | None
    page_count: int | None
    metadata: dict[str, object]


class KnowledgeDocumentParser:
    """Validate type signatures and extract bounded plain text."""

    def parse(self, *, data: bytes, filename: str, mime_type: str) -> ParsedDocument:
        if not data:
            raise BadRequestError(message="Document is empty", code="DOCUMENT_EMPTY")
        extension = Path(filename).suffix.lower()
        allowed_mimes = _MIME_BY_EXTENSION.get(extension)
        if allowed_mimes is None:
            raise BadRequestError(
                message="Unsupported document extension", code="DOCUMENT_TYPE_UNSUPPORTED"
            )
        normalized_mime = mime_type.split(";", 1)[0].strip().lower()
        if normalized_mime not in allowed_mimes:
            raise BadRequestError(
                message="Document MIME type does not match its extension",
                code="DOCUMENT_MIME_MISMATCH",
            )
        if extension == ".pdf":
            if not data.startswith(b"%PDF-"):
                raise BadRequestError(
                    message="Invalid PDF signature", code="DOCUMENT_SIGNATURE_MISMATCH"
                )
            return self._parse_pdf(data)
        if extension == ".docx":
            self._validate_docx_container(data)
            return self._parse_docx(data)
        return self._parse_text(data, extension)

    def _parse_pdf(self, data: bytes) -> ParsedDocument:
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except Exception:
            return self._failed("PDF_CORRUPT")
        try:
            if document.needs_pass:
                return self._failed("PDF_ENCRYPTED", page_count=document.page_count)
            if document.page_count > MAX_PDF_PAGES:
                return self._failed("PDF_PAGE_LIMIT_EXCEEDED", page_count=document.page_count)
            chunks: list[str] = []
            pages: list[dict[str, int]] = []
            length = 0
            for index in range(document.page_count):
                page = document.load_page(index)
                text = page.get_text("text").strip()
                if text:
                    if chunks:
                        length += 2
                    start = length
                    chunks.append(text)
                    length += len(text)
                else:
                    start = length
                pages.append({"page_number": index + 1, "start": start, "end": length})
                if length > MAX_TEXT_CHARS:
                    return self._failed(
                        "DOCUMENT_TEXT_LIMIT_EXCEEDED", page_count=document.page_count
                    )
            content = "\n\n".join(chunks).strip()
            if not content:
                return self._failed("PDF_NO_EXTRACTABLE_TEXT", page_count=document.page_count)
            return ParsedDocument("ready", content, None, document.page_count, {"pages": pages})
        except Exception:
            return self._failed("PDF_PARSE_FAILED", page_count=document.page_count)
        finally:
            document.close()

    def _validate_docx_container(self, data: bytes) -> None:
        if not data.startswith(b"PK"):
            raise BadRequestError(
                message="Invalid DOCX signature", code="DOCUMENT_SIGNATURE_MISMATCH"
            )
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                names = {member.filename for member in members}
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise BadRequestError(
                        message="Invalid DOCX package", code="DOCUMENT_SIGNATURE_MISMATCH"
                    )
                if len(members) > MAX_ZIP_ENTRIES:
                    raise BadRequestError(
                        message="DOCX archive has too many entries", code="DOCX_ARCHIVE_LIMIT"
                    )
                total = sum(member.file_size for member in members)
                compressed = sum(max(member.compress_size, 1) for member in members)
                if total > MAX_ZIP_UNCOMPRESSED_BYTES or total / compressed > MAX_ZIP_RATIO:
                    raise BadRequestError(
                        message="DOCX archive expansion limit exceeded", code="DOCX_ARCHIVE_LIMIT"
                    )
        except BadRequestError:
            raise
        except (OSError, zipfile.BadZipFile) as exception:
            raise BadRequestError(
                message="Invalid DOCX package", code="DOCUMENT_SIGNATURE_MISMATCH"
            ) from exception

    def _parse_docx(self, data: bytes) -> ParsedDocument:
        try:
            document = Document(io.BytesIO(data))
            chunks = [
                paragraph.text.strip()
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            ]
            table_cells = 0
            for table in document.tables:
                for row in table.rows:
                    values = [cell.text.strip() for cell in row.cells]
                    if any(values):
                        chunks.append("\t".join(values))
                    table_cells += len(values)
            content = "\n".join(chunks).strip()
        except Exception:
            return self._failed("DOCX_PARSE_FAILED")
        if not content:
            return self._failed("DOCX_NO_EXTRACTABLE_TEXT")
        if len(content) > MAX_TEXT_CHARS:
            return self._failed("DOCUMENT_TEXT_LIMIT_EXCEEDED")
        return ParsedDocument(
            "ready",
            content,
            None,
            None,
            {
                "paragraph_count": len(document.paragraphs),
                "table_count": len(document.tables),
                "table_cell_count": table_cells,
            },
        )

    def _parse_text(self, data: bytes, extension: str) -> ParsedDocument:
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            return self._failed("TEXT_NOT_UTF8")
        content = content.strip()
        if not content:
            raise BadRequestError(message="Document contains no content", code="DOCUMENT_EMPTY")
        if len(content) > MAX_TEXT_CHARS:
            return self._failed("DOCUMENT_TEXT_LIMIT_EXCEEDED")
        return ParsedDocument("ready", content, None, None, {"format": extension.lstrip(".")})

    @staticmethod
    def _failed(code: str, *, page_count: int | None = None) -> ParsedDocument:
        return ParsedDocument("failed", None, code, page_count, {})
