"""Health check service: verify connectivity to all core RAG services."""

import asyncio
import re
import time
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Timeout per check (seconds)
_CHECK_TIMEOUT = 10
_INFRA_TIMEOUT = 5


def _sanitize_error(error: Exception, context: str = "model") -> str:
    """Sanitize error message to hide sensitive information."""
    msg = str(error).lower()
    err_type = type(error).__name__

    if any(k in msg for k in ("timeout", "timed out", "deadline")):
        return "连接超时，请检查网络和服务地址"
    if any(k in msg for k in ("connection refused", "econnrefused")):
        return "连接被拒绝，请检查服务是否启动"
    if any(k in msg for k in ("连接被拒绝", "服务未找到", "服务未启动")):
        return str(error)[:100]

    if context == "infra":
        if any(k in msg for k in ("404", "not found")):
            return f"服务未找到，请检查服务地址配置"
        return f"检查失败: {err_type}"

    # Model-specific errors
    if any(k in msg for k in ("401", "invalid", "api_key", "authentication", "unauthorized")):
        return "认证失败，请检查 API Key 配置"
    if any(k in msg for k in ("404", "model_not_found", "does not exist", "not found")):
        return "模型未找到，请检查模型名称配置"
    if any(k in msg for k in ("429", "rate_limit", "too many requests")):
        return "请求过于频繁，请稍后重试"
    if any(k in msg for k in ("403", "forbidden", "permission")):
        return "权限不足，请检查 API Key 权限"
    return f"检查失败: {err_type}"


async def _timed_check(name: str, coro, timeout: float = _CHECK_TIMEOUT, context: str = "model") -> dict:
    """Run a check coroutine with timeout and timing."""
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        latency = int((time.perf_counter() - start) * 1000)
        # Handle dict returns (e.g. reranker with warning)
        if isinstance(result, dict):
            detail = result.get("detail", str(result))
            warning = result.get("warning")
            item = {"name": name, "status": "ok", "detail": detail, "latency_ms": latency}
            if warning:
                item["warning"] = warning
            return item
        return {"name": name, "status": "ok", "detail": str(result), "latency_ms": latency}
    except asyncio.TimeoutError:
        latency = int((time.perf_counter() - start) * 1000)
        return {"name": name, "status": "timeout", "detail": "连接超时，请检查网络和服务地址", "latency_ms": latency}
    except Exception as e:
        latency = int((time.perf_counter() - start) * 1000)
        logger.warning("health_check_failed", check=name, error=str(e)[:200])
        return {"name": name, "status": "error", "detail": _sanitize_error(e, context), "latency_ms": latency}


# --- Individual check functions ---


async def _check_llm_primary() -> str:
    """Check primary LLM model connectivity."""
    from app.services.llm_config import get_llm_api_key, get_llm_base_url, get_llm_model
    from openai import AsyncOpenAI

    model = get_llm_model()
    api_key = get_llm_api_key()
    base_url = get_llm_base_url()
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=1,
    )
    return f"{model} via {'custom' if base_url else 'openai'}"


async def _check_llm_fallback() -> str:
    """Check fallback LLM model connectivity."""
    from app.services.llm_config import get_llm_api_key, get_llm_base_url
    from app.core.config import get_settings
    from openai import AsyncOpenAI

    settings = get_settings()
    model = settings.llm_fallback_model
    api_key = get_llm_api_key()
    base_url = get_llm_base_url()
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=1,
    )
    return model


async def _check_llm_economy() -> str:
    """Check economy LLM model connectivity."""
    from app.services.llm_config import get_llm_api_key, get_llm_base_url
    from app.services.archi_config import get_llm_model_economy
    from openai import AsyncOpenAI

    model = get_llm_model_economy()
    api_key = get_llm_api_key()
    base_url = get_llm_base_url()
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=1,
    )
    return model


async def _check_embedding() -> str:
    """Check embedding model connectivity."""
    from app.services.embedding_config import (
        get_embedding_api_key,
        get_embedding_base_url,
        get_embedding_dimensions,
        get_embedding_model,
        get_embedding_provider_name,
    )
    from openai import AsyncOpenAI

    provider = get_embedding_provider_name()
    model = get_embedding_model()
    dims = get_embedding_dimensions()

    if provider in {"openai", "custom"}:
        api_key = get_embedding_api_key()
        base_url = get_embedding_base_url()
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.embeddings.create(model=model, input=["test"])
        actual_dims = len(resp.data[0].embedding)
        return f"{model} ({actual_dims}d) via {provider}"
    elif provider == "ollama":
        import httpx
        base_url = get_embedding_base_url() or "http://host.docker.internal:11434"
        async with httpx.AsyncClient(timeout=_CHECK_TIMEOUT) as client:
            resp = await client.post(f"{base_url}/api/embeddings", json={"model": model, "prompt": "test"})
            resp.raise_for_status()
            data = resp.json()
            actual_dims = len(data.get("embedding", []))
            return f"{model} ({actual_dims}d) via ollama"
    else:
        return f"{model} via {provider}"


async def _check_reranker() -> dict:
    """Check reranker model connectivity. Returns dict with detail and optional warning."""
    from app.services.reranker_config import (
        get_reranker_api_format,
        get_reranker_api_key,
        get_reranker_base_url,
        get_reranker_model,
        get_reranker_provider,
        get_reranker_url,
    )

    provider = get_reranker_provider()

    if provider == "local":
        import httpx
        url = get_reranker_url()
        model = get_reranker_model()
        async with httpx.AsyncClient(timeout=_CHECK_TIMEOUT) as client:
            resp = await client.post(url, json={
                "query": "test",
                "documents": ["test document"],
                "top_k": 1,
            })
            resp.raise_for_status()
            return {"detail": f"{model} via local ({url})"}
    elif provider == "cloud":
        import httpx
        base_url = get_reranker_base_url()
        api_key = get_reranker_api_key()
        model = get_reranker_model()
        api_format = get_reranker_api_format()
        if not base_url:
            raise ValueError("Cloud reranker base URL not configured")

        if api_format == "openai":
            # Test with a minimal chat completion
            url = f"{base_url}/chat/completions"
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            async with httpx.AsyncClient(timeout=_CHECK_TIMEOUT) as client:
                resp = await client.post(url, json={
                    "model": model,
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 1,
                }, headers=headers)
                resp.raise_for_status()
                return {"detail": f"{model} via openai ({base_url})"}
        else:
            # Test with standard rerank API
            url = f"{base_url}/rerank"
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            payload: dict[str, Any] = {
                "query": "test",
                "documents": ["test document"],
                "top_n": 1,
            }
            if model:
                payload["model"] = model
            async with httpx.AsyncClient(timeout=_CHECK_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return {"detail": f"{model} via rerank API ({base_url})"}
    else:
        # Identity reranker (no-op) — functional but no real reranking
        return {
            "detail": f"无重排序模型 (provider={provider})",
            "warning": "当前使用 identity reranker，检索结果按原始分数排序，无重排序效果。如需重排序，请配置 local 或 cloud provider。",
        }


async def _check_postgres() -> str:
    """Check PostgreSQL connectivity."""
    from sqlalchemy import text
    from app.db.session import engine

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return "connected"


async def _check_redis() -> str:
    """Check Redis connectivity."""
    import redis.asyncio as redis
    settings = get_settings()
    r = redis.from_url(settings.redis_url)
    try:
        await r.ping()
        return "connected"
    finally:
        await r.aclose()


async def _check_qdrant() -> str:
    """Check Qdrant connectivity."""
    import httpx
    settings = get_settings()
    host = settings.qdrant_host
    port = settings.qdrant_port
    url = f"http://{host}:{port}"
    async with httpx.AsyncClient(timeout=_INFRA_TIMEOUT) as client:
        resp = await client.get(f"{url}/")
        resp.raise_for_status()
        data = resp.json()
        version = data.get("version", "unknown")
        return f"connected (v{version})"


async def _check_opensearch() -> str:
    """Check OpenSearch connectivity."""
    import httpx
    settings = get_settings()
    host = settings.opensearch_host
    async with httpx.AsyncClient(timeout=_INFRA_TIMEOUT) as client:
        resp = await client.get(f"{host}/_cluster/health")
        if resp.status_code == 404:
            raise ConnectionError(f"OpenSearch 服务未找到，请检查 opensearch_host 配置 (当前: {host})")
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "unknown")
        return f"cluster: {status}"


# --- Main health check ---


async def run_health_check() -> dict:
    """Run all health checks in parallel and return structured results."""
    checks = await asyncio.gather(
        _timed_check("LLM 主模型", _check_llm_primary()),
        _timed_check("LLM 备用模型", _check_llm_fallback()),
        _timed_check("LLM 经济模型", _check_llm_economy()),
        _timed_check("Embedding 模型", _check_embedding()),
        _timed_check("Reranker 模型", _check_reranker()),
        _timed_check("PostgreSQL", _check_postgres(), _INFRA_TIMEOUT, context="infra"),
        _timed_check("Redis", _check_redis(), _INFRA_TIMEOUT, context="infra"),
        _timed_check("Qdrant", _check_qdrant(), _INFRA_TIMEOUT, context="infra"),
        _timed_check("OpenSearch", _check_opensearch(), _INFRA_TIMEOUT, context="infra"),
    )

    ok_count = sum(1 for c in checks if c["status"] == "ok")
    warning_count = sum(1 for c in checks if c.get("warning"))
    total = len(checks)
    failed = total - ok_count

    if failed > 0 and ok_count < total // 2:
        status = "unhealthy"
    elif failed > 0 or warning_count > 0:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "checks": checks,
        "summary": {"total": total, "ok": ok_count, "failed": failed, "warnings": warning_count},
    }
