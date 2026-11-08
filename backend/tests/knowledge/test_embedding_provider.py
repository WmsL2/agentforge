"""Embedding adapter batching, validation, and safe failure tests."""

from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from app.services.knowledge.embedding.provider import (
    EmbeddingError,
    OpenAIEmbeddingProvider,
    validate_embeddings,
)


class _EmbeddingsEndpoint:
    def __init__(self, *, failures: int = 0):
        self.calls: list[list[str]] = []
        self.failures = failures

    async def create(self, *, model, input, dimensions):
        self.calls.append(input)
        if len(self.calls) <= self.failures:
            raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        return SimpleNamespace(
            model=model,
            data=[
                SimpleNamespace(index=index, embedding=[float(index + 1)] * dimensions)
                for index, _ in enumerate(input)
            ],
        )


def _provider(endpoint: _EmbeddingsEndpoint, **kwargs):
    return OpenAIEmbeddingProvider(
        api_key="test-key",
        model="text-embedding-3-small",
        dimensions=1536,
        base_url=None,
        batch_size=kwargs.get("batch_size", 2),
        timeout_seconds=1,
        max_retries=kwargs.get("max_retries", 0),
        client=SimpleNamespace(embeddings=endpoint),
    )


@pytest.mark.anyio
async def test_batches_requests_and_preserves_count() -> None:
    endpoint = _EmbeddingsEndpoint()
    vectors = await _provider(endpoint).embed_documents(["a", "b", "c", "d", "e"])
    assert [len(call) for call in endpoint.calls] == [2, 2, 1]
    assert len(vectors) == 5
    assert all(len(vector) == 1536 for vector in vectors)


@pytest.mark.anyio
async def test_timeout_retries_are_bounded_and_safe() -> None:
    endpoint = _EmbeddingsEndpoint(failures=2)
    vectors = await _provider(endpoint, max_retries=2).embed_documents(["a"])
    assert len(endpoint.calls) == 3
    assert vectors

    endpoint = _EmbeddingsEndpoint(failures=3)
    with pytest.raises(EmbeddingError, match="EMBEDDING_TIMEOUT") as captured:
        await _provider(endpoint, max_retries=1).embed_documents(["a"])
    assert captured.value.retryable is True
    assert len(endpoint.calls) == 2


@pytest.mark.parametrize(
    ("vectors", "count", "dimensions", "code"),
    [
        ([], 1, 2, "EMBEDDING_COUNT_MISMATCH"),
        ([[1.0]], 1, 2, "EMBEDDING_DIMENSION_MISMATCH"),
        ([[float("nan"), 1.0]], 1, 2, "EMBEDDING_VALUE_INVALID"),
        ([[float("inf"), 1.0]], 1, 2, "EMBEDDING_VALUE_INVALID"),
        ([[0.0, 0.0]], 1, 2, "EMBEDDING_ZERO_VECTOR"),
    ],
)
def test_invalid_provider_results_are_rejected(vectors, count, dimensions, code) -> None:
    with pytest.raises(EmbeddingError, match=code):
        validate_embeddings(vectors, expected_count=count, dimensions=dimensions)


def test_missing_key_and_incompatible_dimensions_fail_closed() -> None:
    with pytest.raises(EmbeddingError, match="EMBEDDING_API_KEY_MISSING"):
        OpenAIEmbeddingProvider(
            api_key="",
            model="text-embedding-3-small",
            dimensions=1536,
            base_url=None,
            batch_size=32,
            timeout_seconds=30,
            max_retries=2,
        )


@pytest.mark.anyio
async def test_provider_response_model_mismatch_is_not_success() -> None:
    endpoint = _EmbeddingsEndpoint()
    original_create = endpoint.create

    async def wrong_model(**kwargs):
        response = await original_create(**kwargs)
        response.model = "unexpected-model"
        return response

    endpoint.create = wrong_model
    with pytest.raises(EmbeddingError, match="EMBEDDING_MODEL_MISMATCH"):
        await _provider(endpoint).embed_documents(["a"])
    with pytest.raises(EmbeddingError, match="EMBEDDING_DIMENSIONS_INCOMPATIBLE"):
        OpenAIEmbeddingProvider(
            api_key="x",
            model="other",
            dimensions=3,
            base_url=None,
            batch_size=32,
            timeout_seconds=30,
            max_retries=2,
        )
