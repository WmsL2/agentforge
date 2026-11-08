"""Validated, bounded OpenAI-compatible document embeddings."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from numbers import Real
from typing import Protocol

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)


class EmbeddingProvider(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingError(RuntimeError):
    def __init__(self, safe_code: str, *, retryable: bool = False) -> None:
        self.safe_code = safe_code
        self.retryable = retryable
        super().__init__(safe_code)


class OpenAIEmbeddingProvider:
    """Direct OpenAI SDK adapter; never substitutes a fake provider."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimensions: int,
        base_url: str | None,
        batch_size: int,
        timeout_seconds: float,
        max_retries: int,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not api_key:
            raise EmbeddingError("EMBEDDING_API_KEY_MISSING")
        if dimensions != 1536:
            raise EmbeddingError("EMBEDDING_DIMENSIONS_INCOMPATIBLE")
        if not model or batch_size <= 0 or timeout_seconds <= 0 or max_retries < 0:
            raise EmbeddingError("EMBEDDING_CONFIGURATION_INVALID")
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self._batch_size):
            batch = texts[offset : offset + self._batch_size]
            vectors.extend(await self._embed_batch(batch))
        return validate_embeddings(vectors, expected_count=len(texts), dimensions=self.dimensions)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        for attempt in range(self._max_retries + 1):
            retry_error: Exception | None = None
            try:
                response = await self._client.embeddings.create(
                    model=self.model,
                    input=texts,
                    dimensions=self.dimensions,
                )
                response_model = getattr(response, "model", self.model)
                if response_model != self.model:
                    raise EmbeddingError("EMBEDDING_MODEL_MISMATCH")
                ordered = sorted(response.data, key=lambda item: item.index)
                return validate_embeddings(
                    [list(item.embedding) for item in ordered],
                    expected_count=len(texts),
                    dimensions=self.dimensions,
                )
            except RateLimitError as error:
                code = "EMBEDDING_RATE_LIMITED"
                retryable = True
                retry_error = error
            except APITimeoutError as error:
                code = "EMBEDDING_TIMEOUT"
                retryable = True
                retry_error = error
            except (APIConnectionError, InternalServerError) as error:
                code = "EMBEDDING_PROVIDER_UNAVAILABLE"
                retryable = True
                retry_error = error
            except EmbeddingError:
                raise
            except Exception as error:
                raise EmbeddingError("EMBEDDING_PROVIDER_REJECTED") from error
            if attempt >= self._max_retries:
                raise EmbeddingError(code, retryable=retryable) from retry_error
            await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
        raise AssertionError("unreachable")


def validate_embeddings(
    vectors: Sequence[Sequence[float]], *, expected_count: int, dimensions: int
) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise EmbeddingError("EMBEDDING_COUNT_MISMATCH")
    validated: list[list[float]] = []
    for vector in vectors:
        if len(vector) != dimensions:
            raise EmbeddingError("EMBEDDING_DIMENSION_MISMATCH")
        if not all(isinstance(value, Real) and not isinstance(value, bool) for value in vector):
            raise EmbeddingError("EMBEDDING_VALUE_INVALID")
        values = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in values):
            raise EmbeddingError("EMBEDDING_VALUE_INVALID")
        if not any(value != 0.0 for value in values):
            raise EmbeddingError("EMBEDDING_ZERO_VECTOR")
        validated.append(values)
    return validated
