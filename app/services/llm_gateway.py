"""Pluggable LLM gateway - OpenAI with fallback, cache, token budget."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
import asyncio
import hashlib
import json
import time

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.llm_config import get_llm_api_key, get_llm_base_url, get_llm_fallback_model, get_llm_model

logger = get_logger(__name__)


def _record_llm_attempt(
    event: dict[str, Any],
    *,
    messages: list[dict[str, str]] | None = None,
    response: "LLMResponse | None" = None,
) -> None:
    """Best-effort structured logging for one real provider attempt.

    Always records lightweight telemetry (task, model, attempt, duration, status,
    error_type, is_fallback) to llm_call_log_var. Only adds heavy fields
    (messages, response_content, tokens, cost) when debug_llm_calls is enabled.
    """
    try:
        logger.info("llm_attempt_completed", **event)
    except Exception:
        pass

    try:
        from app.core.tracing import llm_call_log_var

        log_list = llm_call_log_var.get()
        if log_list is None:
            return

        # Always record lightweight event
        record = dict(event)

        # Only add heavy fields when full capture is enabled
        try:
            from app.services.archi_config import get_debug_llm_calls
            full_capture = get_debug_llm_calls()
        except Exception:
            full_capture = False

        if full_capture and response is not None:
            from app.core.metrics import estimate_cost

            record.update(
                {
                    "messages": [
                        {"role": item.get("role", ""), "content": (item.get("content") or "")[:4000]}
                        for item in (messages or [])
                    ],
                    "response_content": (response.content or "")[:4000],
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost_usd": round(
                        estimate_cost(response.model, response.input_tokens, response.output_tokens),
                        6,
                    ),
                }
            )
        log_list.append(record)
    except Exception:
        pass


def _build_llm_attempt_event(
    *,
    model: str,
    attempt: int,
    duration_seconds: float,
    status: str,
    error: Exception | None = None,
    backoff_attempt: int | None = None,
    wait_seconds: float | None = None,
) -> dict[str, Any]:
    try:
        from app.core.tracing import current_llm_task_var

        task = current_llm_task_var.get() or "unknown"
    except Exception:
        task = "unknown"

    # Detect 429 rate-limit errors for explicit status
    if error is not None:
        error_name = type(error).__name__.lower()
        if isinstance(error, Exception) and ("rate" in error_name or "429" in str(error)):
            status = "rate_limited"

    event: dict[str, Any] = {
        "task": task,
        "model": model,
        "attempt": attempt,
        "is_fallback": attempt > 1,
        "duration_seconds": round(max(0.0, duration_seconds), 6),
        "status": status,
        "error_type": type(error).__name__ if error is not None else None,
    }
    if backoff_attempt is not None:
        event["backoff_attempt"] = backoff_attempt
    if wait_seconds is not None:
        event["wait_seconds"] = round(max(0.0, wait_seconds), 6)
    return event


@dataclass
class LLMResponse:
    """Structured LLM response."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None


class LLMGateway(ABC):
    """Abstract LLM gateway interface."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send chat completion request."""
        pass


_JSON_RESPONSE_TASKS = {
    "doc_type_classifier",
    "doc_type_router",
    "evidence_evaluator",
    "evidence_quality",
    "evidence_selector",
    "generate",
    "generate_reasoning",
    "normalizer",
    "query_rewriter",
    "relevance_check",
    "self_critic",
}


def _current_llm_task() -> str:
    try:
        from app.core.tracing import current_llm_task_var

        return str(current_llm_task_var.get() or "").strip()
    except Exception:
        return ""


def _should_request_json_response(task: str, messages: list[dict[str, str]]) -> bool:
    if task in _JSON_RESPONSE_TASKS:
        return True
    text = "\n".join((item.get("content") or "")[:2000] for item in messages)
    lowered = text.lower()
    return "json" in lowered and ("return only" in lowered or "只返回" in text or "输出必须" in text)


def _is_rate_limit_error(error: Exception) -> bool:
    """Check if an error is a 429 rate-limit error."""
    error_name = type(error).__name__.lower()
    if "rate" in error_name:
        return True
    error_str = str(error).lower()
    return "429" in error_str or "rate limit" in error_str


def _parse_retry_after(error: Exception) -> float | None:
    """Extract Retry-After seconds from an OpenAI 429 error, if present."""
    try:
        # openai.RateLimitError has a .response attribute with headers
        resp = getattr(error, "response", None)
        if resp is not None:
            headers = getattr(resp, "headers", None)
            if headers and "retry-after" in headers:
                val = float(headers["retry-after"])
                return max(0.0, val)
    except (TypeError, ValueError, AttributeError):
        pass
    return None


# Bounded 429 backoff constants
_429_MAX_RETRIES = 2  # max extra retries per model on 429
_429_BASE_DELAY = 2.0  # base delay seconds
_429_MAX_DELAY = 60.0  # cap delay seconds


def _is_response_format_unsupported(error: Exception) -> bool:
    message = str(error).lower()
    if "response_format" not in message:
        return False
    return any(
        marker in message
        for marker in (
            "unsupported",
            "not supported",
            "unknown",
            "unrecognized",
            "invalid",
            "extra inputs are not permitted",
            "unexpected",
        )
    )


def _cache_key(messages: list, model: str, temperature: float, options: dict[str, Any] | None = None) -> str:
    """Generate cache key for request."""
    payload = json.dumps(
        {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "options": options or {},
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class OpenAIGateway(LLMGateway):
    """OpenAI Chat Completions with fallback, cache, retry, token budget."""

    def __init__(self) -> None:
        self._settings = get_settings()
        api_key = get_llm_api_key()
        base_url = get_llm_base_url()
        kwargs: dict = {
            "api_key": api_key,
            "timeout": self._settings.llm_timeout_seconds,
        }
        if base_url and base_url.strip():
            kwargs["base_url"] = base_url.strip()
        self._client = AsyncOpenAI(**kwargs)

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> LLMResponse:
        """Call OpenAI with fallback, cache, retry."""
        model = kwargs.pop("model", None) or get_llm_model()
        models_to_try = [model, get_llm_fallback_model()]
        max_tokens = kwargs.pop("max_tokens", None) or self._settings.llm_max_tokens

        # OpenAI prompt caching: improves cache hit rates for similar prompts
        extra_params: dict[str, Any] = {k: v for k, v in kwargs.items() if k not in ("model", "timeout")}
        task = _current_llm_task()
        if "response_format" not in extra_params and _should_request_json_response(task, messages):
            extra_params["response_format"] = {"type": "json_object"}
        prompt_cache_key = self._settings.llm_prompt_cache_key or f"support_ai:{self._settings.app_name}"
        extra_params["prompt_cache_key"] = prompt_cache_key
        if self._settings.llm_prompt_cache_retention in ("24h", "in_memory"):
            extra_params["prompt_cache_retention"] = self._settings.llm_prompt_cache_retention

        cache_options = {
            "response_format": extra_params.get("response_format"),
            "max_tokens": max_tokens,
        }
        # Cache lookup (Redis)
        request_cache_key = _cache_key(messages, model, temperature, cache_options)
        cached = await self._get_cached(request_cache_key)
        if cached:
            logger.debug("llm_cache_hit", model=model, cache_key=request_cache_key[:12])
            return cached

        def _token_param(m: str) -> dict[str, Any]:
            """Use max_completion_tokens for o1/gpt-5; max_tokens for older models."""
            if m.startswith("o1") or m.startswith("gpt-5"):
                return {"max_completion_tokens": max_tokens}
            return {"max_tokens": max_tokens}

        last_error = None
        for attempt, m in enumerate(models_to_try, start=1):
            attempt_started = time.perf_counter()
            request_params = dict(extra_params)
            try:
                try:
                    response = await self._client.chat.completions.create(
                        model=m,
                        messages=messages,
                        temperature=temperature,
                        **_token_param(m),
                        **request_params,
                    )
                except Exception as inner_error:
                    if "response_format" not in request_params or not _is_response_format_unsupported(inner_error):
                        raise
                    logger.warning(
                        "llm_response_format_unsupported_retrying_prompt_only",
                        model=m,
                        error=str(inner_error),
                    )
                    request_params.pop("response_format", None)
                    response = await self._client.chat.completions.create(
                        model=m,
                        messages=messages,
                        temperature=temperature,
                        **_token_param(m),
                        **request_params,
                    )
                attempt_duration = time.perf_counter() - attempt_started
                choice = response.choices[0] if response.choices else None
                if not choice:
                    raise ValueError("Empty LLM response")

                usage = response.usage or type("Usage", (), {"prompt_tokens": 0, "completion_tokens": 0})()
                inp = getattr(usage, "prompt_tokens", 0)
                out = getattr(usage, "completion_tokens", 0)
                raw_content = choice.message.content or ""
                if not raw_content.strip():
                    # Empty content is not a valid success — treat as provider error so caller retries/falls back.
                    raise ValueError("LLM returned empty content")
                result = LLMResponse(
                    content=raw_content,
                    model=response.model,
                    provider="openai",
                    input_tokens=inp,
                    output_tokens=out,
                    finish_reason=choice.finish_reason,
                    raw={"id": response.id, "model": response.model},
                )
                await self._set_cached(request_cache_key, result)
                logger.debug("llm_cache_store", model=response.model, cache_key=request_cache_key[:12])
                # Metrics
                try:
                    from app.core.metrics import (
                        llm_requests_total,
                        llm_tokens_total,
                        llm_cost_usd,
                        estimate_cost,
                    )
                    llm_requests_total.labels(model=response.model, status="success").inc()
                    llm_tokens_total.labels(model=response.model, type="input").inc(inp)
                    llm_tokens_total.labels(model=response.model, type="output").inc(out)
                    llm_cost_usd.labels(model=response.model).inc(estimate_cost(response.model, inp, out))
                except Exception:
                    pass
                try:
                    from app.core.tracing import llm_usage_var
                    acc = llm_usage_var.get()
                    if acc is not None:
                        acc.append({"model": response.model, "input_tokens": inp, "output_tokens": out})
                except Exception:
                    pass
                event = _build_llm_attempt_event(
                    model=m,
                    attempt=attempt,
                    duration_seconds=attempt_duration,
                    status="success",
                )
                _record_llm_attempt(event, messages=messages, response=result)
                return result
            except Exception as e:
                last_error = e
                error_name = type(e).__name__.lower()
                status = "timeout" if isinstance(e, TimeoutError) or "timeout" in error_name else "error"
                event = _build_llm_attempt_event(
                    model=m,
                    attempt=attempt,
                    duration_seconds=time.perf_counter() - attempt_started,
                    status=status,
                    error=e,
                )
                _record_llm_attempt(event)
                logger.warning("llm_model_failed", model=m, error=str(e))

                # Bounded 429 backoff: retry same model before falling back
                if _is_rate_limit_error(e):
                    retry_after = _parse_retry_after(e)
                    for backoff_attempt in range(1, _429_MAX_RETRIES + 1):
                        delay = min(
                            retry_after if retry_after is not None else _429_BASE_DELAY * (2 ** (backoff_attempt - 1)),
                            _429_MAX_DELAY,
                        )
                        logger.info(
                            "llm_429_backoff",
                            model=m,
                            backoff_attempt=backoff_attempt,
                            delay_seconds=round(delay, 1),
                        )
                        await asyncio.sleep(delay)
                        backoff_started = time.perf_counter()
                        try:
                            response = await self._client.chat.completions.create(
                                model=m,
                                messages=messages,
                                temperature=temperature,
                                **_token_param(m),
                                **request_params,
                            )
                            backoff_duration = time.perf_counter() - backoff_started
                            choice = response.choices[0] if response.choices else None
                            if not choice:
                                raise ValueError("Empty LLM response")
                            usage = response.usage or type("Usage", (), {"prompt_tokens": 0, "completion_tokens": 0})()
                            inp = getattr(usage, "prompt_tokens", 0)
                            out = getattr(usage, "completion_tokens", 0)
                            raw_content = choice.message.content or ""
                            if not raw_content.strip():
                                raise ValueError("LLM returned empty content")
                            result = LLMResponse(
                                content=raw_content,
                                model=response.model,
                                provider="openai",
                                input_tokens=inp,
                                output_tokens=out,
                                finish_reason=choice.finish_reason,
                                raw={"id": response.id, "model": response.model},
                            )
                            await self._set_cached(request_cache_key, result)
                            try:
                                from app.core.metrics import llm_requests_total, llm_tokens_total, llm_cost_usd, estimate_cost
                                llm_requests_total.labels(model=response.model, status="success").inc()
                                llm_tokens_total.labels(model=response.model, type="input").inc(inp)
                                llm_tokens_total.labels(model=response.model, type="output").inc(out)
                                llm_cost_usd.labels(model=response.model).inc(estimate_cost(response.model, inp, out))
                            except Exception:
                                pass
                            event = _build_llm_attempt_event(
                                model=m,
                                attempt=attempt,
                                duration_seconds=backoff_duration,
                                status="success_after_429",
                                backoff_attempt=backoff_attempt,
                                wait_seconds=delay,
                            )
                            _record_llm_attempt(event, messages=messages, response=result)
                            return result
                        except Exception as backoff_e:
                            backoff_event = _build_llm_attempt_event(
                                model=m,
                                attempt=attempt,
                                duration_seconds=time.perf_counter() - backoff_started,
                                status="rate_limited",
                                error=backoff_e,
                                backoff_attempt=backoff_attempt,
                                wait_seconds=delay,
                            )
                            _record_llm_attempt(backoff_event)
                            last_error = backoff_e
                            if not _is_rate_limit_error(backoff_e):
                                break  # non-429 error, stop retrying this model

                if m == models_to_try[-1]:
                    raise last_error

        raise last_error or ValueError("LLM failed")

    async def _get_cached(self, key: str) -> LLMResponse | None:
        """Get from Redis cache. Purges stale empty-content entries on read."""
        r = None
        try:
            import redis.asyncio as redis
            r = redis.from_url(self._settings.redis_url, decode_responses=False)
            redis_key = f"llm_cache:{key}"
            data = await r.get(redis_key)
            if data:
                import pickle
                cached = pickle.loads(data)
                if not (cached.content or "").strip():
                    await r.delete(redis_key)
                    logger.debug("llm_cache_purged_empty", cache_key=key[:12])
                    return None
                return cached
            return None
        except Exception as e:
            logger.debug("llm_cache_get_failed", error=str(e))
            return None
        finally:
            if r is not None:
                try:
                    await r.close()
                except Exception:
                    pass

    async def _set_cached(self, key: str, response: LLMResponse) -> None:
        """Set in Redis cache. Refuses to cache empty-content responses."""
        if not (response.content or "").strip():
            logger.debug("llm_cache_skip_empty_content", cache_key=key[:12])
            return
        r = None
        try:
            import redis.asyncio as redis
            import pickle
            r = redis.from_url(self._settings.redis_url, decode_responses=False)
            await r.setex(
                f"llm_cache:{key}",
                self._settings.llm_cache_ttl_seconds,
                pickle.dumps(response),
            )
        except Exception as e:
            logger.debug("llm_cache_set_failed", error=str(e))
        finally:
            if r is not None:
                try:
                    await r.close()
                except Exception:
                    pass


async def clear_llm_cache() -> dict[str, int]:
    """Clear Redis-backed LLM cache namespace."""
    settings = get_settings()
    r = None
    try:
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url, decode_responses=False)
        keys = await r.keys("llm_cache:*")
        deleted = 0
        if keys:
            deleted = int(await r.delete(*keys))
        logger.info("llm_cache_cleared", deleted_keys=deleted)
        return {"deleted_keys": deleted}
    except Exception as e:
        logger.warning("llm_cache_clear_failed", error=str(e))
        return {"deleted_keys": 0}
    finally:
        if r is not None:
            try:
                await r.close()
            except Exception:
                pass


async def purge_empty_llm_cache() -> dict[str, int]:
    """Selectively remove only empty-content entries from LLM cache.

    Less destructive than clear_llm_cache(): valid cached responses are kept.
    """
    settings = get_settings()
    r = None
    try:
        import pickle
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url, decode_responses=False)
        keys = await r.keys("llm_cache:*")
        purged = 0
        for redis_key in keys:
            data = await r.get(redis_key)
            if not data:
                continue
            try:
                cached = pickle.loads(data)
                if not (getattr(cached, "content", None) or "").strip():
                    await r.delete(redis_key)
                    purged += 1
            except Exception:
                # Corrupt entry — also remove.
                await r.delete(redis_key)
                purged += 1
        logger.info("llm_cache_purged_empty", purged_keys=purged, total_keys=len(keys))
        return {"purged_keys": purged, "total_keys": len(keys)}
    except Exception as e:
        logger.warning("llm_cache_purge_failed", error=str(e))
        return {"purged_keys": 0, "total_keys": 0}
    finally:
        if r is not None:
            try:
                await r.close()
            except Exception:
                pass


def get_llm_gateway() -> LLMGateway:
    """Factory for LLM gateway."""
    settings = get_settings()
    if settings.llm_provider == "openai":
        return OpenAIGateway()
    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
