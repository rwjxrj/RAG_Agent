"""Reranker providers: local HTTP, cloud API (rerank/OpenAI format), or identity."""

import httpx
from typing import Any

from app.core.logging import get_logger
from app.search.base import RerankerProvider, SearchChunk

logger = get_logger(__name__)


class LocalRerankerProvider(RerankerProvider):
    """Local HTTP reranker service (e.g. sentence-transformers cross-encoder)."""

    async def rerank(
        self, query: str, chunks: list[SearchChunk], top_k: int
    ) -> list[tuple[SearchChunk, float]]:
        """Call local reranker endpoint."""
        from app.services.reranker_config import get_reranker_url

        if not chunks:
            return []

        url = f"{get_reranker_url().rstrip('/')}/rerank"
        payload = {
            "query": query,
            "documents": [c.chunk_text for c in chunks],
            "top_k": min(top_k, len(chunks)),
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning("reranker_failed", error=str(e))
            return [(c, c.score) for c in chunks[:top_k]]

        results = data.get("results", [])
        if not results:
            return [(c, c.score) for c in chunks[:top_k]]

        chunk_map = {i: c for i, c in enumerate(chunks)}
        out: list[tuple[SearchChunk, float]] = []
        for r in results:
            idx = r.get("index", -1)
            score = r.get("relevance_score", 0.0)
            if idx in chunk_map:
                out.append((chunk_map[idx], score))
        return out[:top_k]


class CloudRerankerProvider(RerankerProvider):
    """Generic cloud reranker: supports 'rerank' API format and 'openai' chat format.

    Rerank format (Cohere/Jina/SiliconFlow/any compatible):
        POST {base_url}/rerank
        Body: {"query": ..., "documents": [...], "top_n": ..., "model": ...}
        Response: {"results": [{"index": ..., "relevance_score": ...}]}

    OpenAI format:
        POST {base_url}/chat/completions
        Body: {"model": ..., "messages": [...], "response_format": {...}}
        Response: {"choices": [{"message": {"content": ...}}]}
    """

    async def rerank(
        self, query: str, chunks: list[SearchChunk], top_k: int
    ) -> list[tuple[SearchChunk, float]]:
        from app.services.reranker_config import (
            get_reranker_api_format,
            get_reranker_api_key,
            get_reranker_base_url,
            get_reranker_model,
        )

        if not chunks:
            return []

        api_format = get_reranker_api_format()
        base_url = get_reranker_base_url().rstrip("/")
        api_key = get_reranker_api_key()
        model = get_reranker_model()

        if not base_url:
            logger.warning("cloud_reranker_no_base_url")
            return [(c, c.score) for c in chunks[:top_k]]

        try:
            if api_format == "openai":
                return await self._rerank_openai(query, chunks, top_k, base_url, api_key, model)
            else:
                return await self._rerank_api(query, chunks, top_k, base_url, api_key, model)
        except Exception as e:
            logger.warning("cloud_reranker_failed", error=str(e))
            return [(c, c.score) for c in chunks[:top_k]]

    async def _rerank_api(
        self,
        query: str,
        chunks: list[SearchChunk],
        top_k: int,
        base_url: str,
        api_key: str,
        model: str,
    ) -> list[tuple[SearchChunk, float]]:
        """Standard rerank API format (Cohere/Jina/SiliconFlow)."""
        url = f"{base_url}/rerank"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "query": query,
            "documents": [c.chunk_text for c in chunks],
            "top_n": min(top_k, len(chunks)),
        }
        if model:
            payload["model"] = model

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            return [(c, c.score) for c in chunks[:top_k]]

        chunk_map = {i: c for i, c in enumerate(chunks)}
        out: list[tuple[SearchChunk, float]] = []
        for r in results:
            idx = r.get("index", -1)
            score = float(r.get("relevance_score", 0.0))
            if idx in chunk_map:
                out.append((chunk_map[idx], score))
        return out[:top_k]

    async def _rerank_openai(
        self,
        query: str,
        chunks: list[SearchChunk],
        top_k: int,
        base_url: str,
        api_key: str,
        model: str,
    ) -> list[tuple[SearchChunk, float]]:
        """OpenAI chat/completions format for reranking."""
        url = f"{base_url}/chat/completions"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Build document list for the prompt
        doc_lines = []
        for i, c in enumerate(chunks):
            text = (c.chunk_text or "")[:500]
            doc_lines.append(f"[{i}] {text}")
        doc_block = "\n".join(doc_lines)

        prompt = (
            f"Rank the following documents by relevance to the query. "
            f"Return a JSON array of objects with 'index' (int) and 'relevance_score' (float 0-1) fields, "
            f"sorted by relevance_score descending. Return at most {top_k} results.\n\n"
            f"Query: {query}\n\n"
            f"Documents:\n{doc_block}"
        )

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 1000,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse JSON from response
        import json
        import re
        json_match = re.search(r'\[.*?\]', content, re.DOTALL)
        if not json_match:
            return [(c, c.score) for c in chunks[:top_k]]

        try:
            ranked = json.loads(json_match.group())
        except json.JSONDecodeError:
            return [(c, c.score) for c in chunks[:top_k]]

        chunk_map = {i: c for i, c in enumerate(chunks)}
        out: list[tuple[SearchChunk, float]] = []
        for r in ranked:
            idx = r.get("index", -1)
            score = float(r.get("relevance_score", 0.0))
            if idx in chunk_map:
                out.append((chunk_map[idx], score))
        return out[:top_k]


class IdentityRerankerProvider(RerankerProvider):
    """No-op reranker: returns chunks sorted by original score."""

    async def rerank(
        self, query: str, chunks: list[SearchChunk], top_k: int
    ) -> list[tuple[SearchChunk, float]]:
        """Sort by score and return top_k."""
        sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
        return [(c, c.score) for c in sorted_chunks[:top_k]]


def get_reranker_provider() -> RerankerProvider:
    """Factory for reranker based on config."""
    from app.services.reranker_config import get_reranker_provider as _get_provider

    provider = _get_provider()
    if provider == "cloud":
        return CloudRerankerProvider()
    if provider == "local":
        return LocalRerankerProvider()
    return IdentityRerankerProvider()
