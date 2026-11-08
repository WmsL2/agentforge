"""Pure deterministic chunking and source-location tests."""

import pytest

from app.services.knowledge.chunking import (
    ChunkingConfig,
    ChunkLimitExceededError,
    chunk_document,
)


@pytest.mark.parametrize(
    "content",
    [
        "这是一个用于验证字符偏移的中文段落。" * 10,
        "English words and punctuation. " * 12,
        "# Heading\n\n- first\n- second\n\n```python\nprint('x')\n```",
    ],
)
def test_chunks_are_deterministic_exact_python_character_slices(content: str) -> None:
    config = ChunkingConfig(chunk_size=45, overlap=9, max_chunks=100)
    first = chunk_document(content, {}, config)
    assert first == chunk_document(content, {}, config)
    assert first
    assert all(chunk.content == content[chunk.start_offset : chunk.end_offset] for chunk in first)
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))


def test_whitespace_is_not_emitted_and_boundaries_terminate() -> None:
    assert chunk_document(" \n\t ", {}, ChunkingConfig()) == []
    chunks = chunk_document("  abc  def  ", {}, ChunkingConfig(chunk_size=5, overlap=2))
    assert all(chunk.content and not chunk.content.isspace() for chunk in chunks)
    assert all(chunk.start_offset < chunk.end_offset for chunk in chunks)


def test_overlap_and_pdf_single_and_cross_page_mapping() -> None:
    content = "abcdefghijKLMNOPQRST"
    pages = {
        "pages": [
            {"page_number": 1, "start": 0, "end": 10},
            {"page_number": 2, "start": 10, "end": 20},
        ]
    }
    chunks = chunk_document(content, pages, ChunkingConfig(chunk_size=12, overlap=4))
    assert [(chunk.start_offset, chunk.end_offset) for chunk in chunks] == [
        (0, 12),
        (8, 20),
    ]
    assert [(chunk.page_start, chunk.page_end) for chunk in chunks] == [(1, 2), (1, 2)]
    single = chunk_document(content, pages, ChunkingConfig(chunk_size=10, overlap=0))
    assert [(chunk.page_start, chunk.page_end) for chunk in single] == [(1, 1), (2, 2)]


def test_non_pdf_has_no_page_mapping_and_malformed_metadata_is_ignored() -> None:
    chunks = chunk_document(
        "hello world",
        {"pages": [{"page_number": "one", "start": 0, "end": 5}]},
        ChunkingConfig(chunk_size=6, overlap=1),
    )
    assert all((chunk.page_start, chunk.page_end) == (None, None) for chunk in chunks)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chunk_size": 0},
        {"chunk_size": 10, "overlap": -1},
        {"chunk_size": 10, "overlap": 10},
        {"max_chunks": 0},
        {"chunk_size": True},
    ],
)
def test_invalid_config_is_rejected(kwargs) -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(**kwargs)


def test_maximum_chunk_count_is_enforced() -> None:
    with pytest.raises(ChunkLimitExceededError):
        chunk_document("abcdefghij", {}, ChunkingConfig(chunk_size=4, overlap=1, max_chunks=2))
