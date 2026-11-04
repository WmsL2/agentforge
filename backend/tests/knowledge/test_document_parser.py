"""Unit tests for bounded knowledge document parsing."""

import io
from zipfile import ZIP_DEFLATED, ZipFile

import pymupdf
import pytest
from docx import Document

from app.core.exceptions import BadRequestError
from app.services.knowledge.document_parser import KnowledgeDocumentParser


def _pdf(text: str = "Hello PDF", *, pages: int = 1) -> bytes:
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _docx(*, paragraph: str = "Hello DOCX", table: bool = False) -> bytes:
    document = Document()
    if paragraph:
        document.add_paragraph(paragraph)
    if table:
        item = document.add_table(rows=1, cols=2)
        item.cell(0, 0).text = "A"
        item.cell(0, 1).text = "B"
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize(
    ("filename", "mime", "data", "expected"),
    [
        ("a.txt", "text/plain", b"hello", "hello"),
        ("a.md", "text/markdown", b"# title", "# title"),
        ("a.pdf", "application/pdf", _pdf(), "Hello PDF"),
        (
            "a.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _docx(table=True),
            "A\tB",
        ),
    ],
    ids=["txt", "markdown", "pdf", "docx"],
)
def test_supported_documents_are_parsed(filename, mime, data, expected) -> None:
    result = KnowledgeDocumentParser().parse(data=data, filename=filename, mime_type=mime)
    assert result.status == "ready"
    assert expected in (result.content or "")


@pytest.mark.parametrize(
    ("filename", "mime", "data", "code"),
    [
        ("a.exe", "application/octet-stream", b"x", "DOCUMENT_TYPE_UNSUPPORTED"),
        ("a.pdf", "application/pdf", b"not pdf", "DOCUMENT_SIGNATURE_MISMATCH"),
        ("a.txt", "application/pdf", b"text", "DOCUMENT_MIME_MISMATCH"),
        ("a.txt", "text/plain", b"", "DOCUMENT_EMPTY"),
        (
            "a.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PKbad",
            "DOCUMENT_SIGNATURE_MISMATCH",
        ),
    ],
    ids=["extension", "pdf-signature", "mime", "empty", "docx-signature"],
)
def test_direct_validation_rejections(filename, mime, data, code) -> None:
    with pytest.raises(BadRequestError) as error:
        KnowledgeDocumentParser().parse(data=data, filename=filename, mime_type=mime)
    assert error.value.code == code


def test_non_utf8_and_scanned_pdf_are_persistable_failures() -> None:
    parser = KnowledgeDocumentParser()
    text = parser.parse(data=b"\xff", filename="a.txt", mime_type="text/plain")
    scanned = parser.parse(data=_pdf(""), filename="a.pdf", mime_type="application/pdf")
    assert (text.status, text.error_code) == ("failed", "TEXT_NOT_UTF8")
    assert (scanned.status, scanned.error_code) == ("failed", "PDF_NO_EXTRACTABLE_TEXT")


def test_utf8_chinese_text_is_preserved() -> None:
    result = KnowledgeDocumentParser().parse(
        data="知识库文档".encode(), filename="中文.md", mime_type="text/markdown"
    )
    assert result.content == "知识库文档"


def test_pdf_page_metadata_has_stable_offsets() -> None:
    result = KnowledgeDocumentParser().parse(
        data=_pdf("page", pages=2), filename="a.pdf", mime_type="application/pdf"
    )
    pages = result.metadata["pages"]
    assert result.page_count == 2
    assert isinstance(pages, list) and [page["page_number"] for page in pages] == [1, 2]
    assert all((result.content or "")[page["start"] : page["end"]] == "page" for page in pages)


def test_zip_bomb_ratio_is_rejected() -> None:
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "x")
        archive.writestr("word/document.xml", "0" * (1024 * 1024))
    with pytest.raises(BadRequestError) as error:
        KnowledgeDocumentParser().parse(
            data=stream.getvalue(),
            filename="a.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    assert error.value.code == "DOCX_ARCHIVE_LIMIT"


def test_corrupt_encrypted_and_page_limited_pdfs_are_failed_records() -> None:
    parser = KnowledgeDocumentParser()
    corrupt = parser.parse(data=b"%PDF-corrupt", filename="a.pdf", mime_type="application/pdf")
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "secret")
    encrypted_bytes = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    document.close()
    encrypted = parser.parse(data=encrypted_bytes, filename="a.pdf", mime_type="application/pdf")
    too_many = parser.parse(data=_pdf("", pages=201), filename="a.pdf", mime_type="application/pdf")
    assert (corrupt.status, corrupt.error_code) == ("failed", "PDF_CORRUPT")
    assert (encrypted.status, encrypted.error_code) == ("failed", "PDF_ENCRYPTED")
    assert (too_many.status, too_many.error_code) == ("failed", "PDF_PAGE_LIMIT_EXCEEDED")


def test_empty_docx_and_text_character_limit_are_failed_records() -> None:
    parser = KnowledgeDocumentParser()
    empty_docx = parser.parse(
        data=_docx(paragraph=""),
        filename="a.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    too_long = parser.parse(data=(b"x" * 2_000_001), filename="a.txt", mime_type="text/plain")
    assert (empty_docx.status, empty_docx.error_code) == (
        "failed",
        "DOCX_NO_EXTRACTABLE_TEXT",
    )
    assert (too_long.status, too_long.error_code) == (
        "failed",
        "DOCUMENT_TEXT_LIMIT_EXCEEDED",
    )
