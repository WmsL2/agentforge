"""Deterministic character-based document chunking with source locations."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_size: int = 1000
    overlap: int = 150
    max_chunks: int = 2500

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_size, int) or isinstance(self.chunk_size, bool):
            raise ValueError("chunk_size must be an integer")
        if not isinstance(self.overlap, int) or isinstance(self.overlap, bool):
            raise ValueError("overlap must be an integer")
        if not isinstance(self.max_chunks, int) or isinstance(self.max_chunks, bool):
            raise ValueError("max_chunks must be an integer")
        if self.chunk_size <= 0 or self.overlap < 0 or self.overlap >= self.chunk_size:
            raise ValueError("require chunk_size > 0 and 0 <= overlap < chunk_size")
        if self.max_chunks <= 0:
            raise ValueError("max_chunks must be positive")

    @property
    def version(self) -> str:
        return f"character-v1:{self.chunk_size}:{self.overlap}:{self.max_chunks}"


@dataclass(frozen=True)
class DocumentChunk:
    chunk_index: int
    content: str
    start_offset: int
    end_offset: int
    page_start: int | None
    page_end: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


class ChunkLimitExceededError(ValueError):
    pass


def chunk_document(
    parsed_content: str,
    parse_metadata: dict[str, object] | None,
    config: ChunkingConfig,
) -> list[DocumentChunk]:
    """Split by Python character offsets; whitespace is trimmed with offsets adjusted."""
    if not parsed_content or not parsed_content.strip():
        return []
    pages = _valid_pages(parse_metadata)
    chunks: list[DocumentChunk] = []
    raw_start = 0
    content_length = len(parsed_content)
    while raw_start < content_length:
        raw_end = min(raw_start + config.chunk_size, content_length)
        start = raw_start
        end = raw_end
        while start < end and parsed_content[start].isspace():
            start += 1
        while end > start and parsed_content[end - 1].isspace():
            end -= 1
        if start < end:
            if len(chunks) >= config.max_chunks:
                raise ChunkLimitExceededError("document exceeds configured chunk limit")
            page_start, page_end = _page_range(start, end, pages)
            chunks.append(
                DocumentChunk(
                    chunk_index=len(chunks),
                    content=parsed_content[start:end],
                    start_offset=start,
                    end_offset=end,
                    page_start=page_start,
                    page_end=page_end,
                    metadata={},
                )
            )
        if raw_end == content_length:
            break
        raw_start = raw_end - config.overlap
    return chunks


def _valid_pages(metadata: dict[str, object] | None) -> list[tuple[int, int, int]]:
    if not metadata:
        return []
    raw_pages = metadata.get("pages")
    if not isinstance(raw_pages, list):
        return []
    pages: list[tuple[int, int, int]] = []
    for item in raw_pages:
        if not isinstance(item, dict):
            continue
        page_number, start, end = item.get("page_number"), item.get("start"), item.get("end")
        if (
            all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in (page_number, start, end)
            )
            and page_number >= 1
            and start >= 0
            and end >= start
        ):
            pages.append((page_number, start, end))
    return sorted(pages, key=lambda page: (page[1], page[2], page[0]))


def _page_range(
    start: int, end: int, pages: list[tuple[int, int, int]]
) -> tuple[int | None, int | None]:
    matched = [
        number for number, page_start, page_end in pages if start < page_end and end > page_start
    ]
    return (min(matched), max(matched)) if matched else (None, None)
