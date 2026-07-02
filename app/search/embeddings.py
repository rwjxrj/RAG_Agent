"""Embedding providers: OpenAI-compatible or Ollama."""

import httpx
from openai import AsyncOpenAI

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


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embeddings."""

    def __init__(self) -> None:
        api_key = get_embedding_api_key()
        base_url = get_embedding_base_url()
        kwargs: dict = {"api_key": api_key}
        if base_url and base_url.strip():
            kwargs["base_url"] = base_url.strip().rstrip("/")
        self._client = AsyncOpenAI(**kwargs)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using OpenAI."""
        if not texts:
            return []

        try:
            request: dict = {
                "model": get_embedding_model(),
                "input": texts,
            }
            if get_embedding_provider_name() == "aliyun":
                request["dimensions"] = get_embedding_dimensions()
            response = await self._client.embeddings.create(**request)
            return [d.embedding for d in response.data]
        except Exception as e:
            logger.error("embedding_failed", error=str(e))
            raise

    def dimensions(self) -> int:
        return get_embedding_dimensions()


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
