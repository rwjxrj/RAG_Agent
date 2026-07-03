"""Embedding providers: OpenAI-compatible or Ollama."""

import asyncio

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from app.core.config import get_settings
from app.core.logging import get_logger
from app.search.base import EmbeddingProvider
from app.services.embedding_config import (
    get_embedding_api_key,
    get_embedding_base_url,
    get_embedding_dimensions,
    get_embedding_model,
    get_embedding_provider_name,
)

logger = get_logger(__name__)


def _is_retryable_embedding_error(error: Exception) -> bool:
    if isinstance(error, (APIConnectionError, APITimeoutError)):
        return True
    status_code = getattr(error, "status_code", None)
    return status_code in {408, 409, 429} or (
        isinstance(status_code, int) and status_code >= 500
    )


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embeddings."""

    def __init__(self) -> None:
        settings = get_settings()
        self._provider_name = get_embedding_provider_name()
        api_key = get_embedding_api_key()
        base_url = get_embedding_base_url()
        kwargs: dict = {
            "api_key": api_key,
            "max_retries": 0,
            "timeout": settings.embedding_request_timeout_seconds,
        }
        if base_url and base_url.strip():
            kwargs["base_url"] = base_url.strip().rstrip("/")
        self._client = AsyncOpenAI(**kwargs)
        self._retry_attempts = settings.embedding_retry_attempts
        self._retry_backoff_seconds = settings.embedding_retry_backoff_seconds

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using OpenAI."""
        if not texts:
            return []

        request: dict = {
            "model": get_embedding_model(),
            "input": texts,
        }
        if self._provider_name == "aliyun":
            request["dimensions"] = get_embedding_dimensions()

        for attempt in range(1, self._retry_attempts + 1):
            try:
                response = await self._client.embeddings.create(**request)
                return [d.embedding for d in response.data]
            except Exception as error:
                if attempt >= self._retry_attempts or not _is_retryable_embedding_error(error):
                    logger.error(
                        "embedding_failed",
                        error=str(error),
                        attempts=attempt,
                    )
                    raise
                delay = self._retry_backoff_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "embedding_retry_scheduled",
                    error=error.__class__.__name__,
                    attempt=attempt,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)

        raise RuntimeError("Embedding retry loop exited unexpectedly")

    def dimensions(self) -> int:
        return get_embedding_dimensions()

    def max_batch_size(self) -> int | None:
        return 10 if self._provider_name == "aliyun" else None


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama embeddings via /api/embeddings."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using Ollama."""
        if not texts:
            return []

        base_url = get_embedding_base_url().strip().rstrip("/")
        model = get_embedding_model()
        vectors: list[list[float]] = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                for text in texts:
                    response = await client.post(
                        f"{base_url}/api/embeddings",
                        json={"model": model, "prompt": text},
                    )
                    response.raise_for_status()
                    data = response.json()
                    vector = data.get("embedding")
                    if not isinstance(vector, list):
                        raise ValueError("Ollama embedding response missing embedding list")
                    vectors.append(vector)
            return vectors
        except Exception as e:
            logger.error("ollama_embedding_failed", error=str(e))
            raise

    def dimensions(self) -> int:
        return get_embedding_dimensions()


def get_embedding_provider() -> EmbeddingProvider:
    """Factory for embedding provider."""
    provider = get_embedding_provider_name()
    if provider in {"openai", "custom", "aliyun"}:
        return OpenAIEmbeddingProvider()
    if provider == "ollama":
        return OllamaEmbeddingProvider()
    raise ValueError(f"Unknown embedding provider: {provider}")
