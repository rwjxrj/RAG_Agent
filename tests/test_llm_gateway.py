"""Tests for OpenAI gateway cache-key behavior."""

from types import SimpleNamespace

import httpx
import openai
import pytest

from app.services.llm_gateway import LLMResponse, OpenAIGateway, _cache_key, clear_llm_cache
from app.core.tracing import current_llm_task_var, llm_call_log_var


class _Settings:
    llm_max_tokens = 256
    llm_timeout_seconds = 30.0
    llm_prompt_cache_key = "shared-prompt-cache-key"
    llm_prompt_cache_retention = "in_memory"
    llm_cache_ttl_seconds = 3600
    redis_url = "redis://localhost:6379/0"
    app_name = "SupportAI"


def _build_gateway(fake_create):
    gateway = OpenAIGateway.__new__(OpenAIGateway)
    gateway._settings = _Settings()
    gateway._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        )
    )
    return gateway


def _successful_response(model: str):
    return SimpleNamespace(
        id="resp-1",
        model=model,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
    )


async def _disable_gateway_cache(gateway):
    async def fake_get_cached(key):
        return None

    async def fake_set_cached(key, response):
        return None

    gateway._get_cached = fake_get_cached
    gateway._set_cached = fake_set_cached


@pytest.mark.asyncio
async def test_chat_records_successful_model_attempt(monkeypatch):
    async def fake_create(**kwargs):
        return _successful_response(kwargs["model"])

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")
    monkeypatch.setattr("app.services.archi_config.get_debug_llm_calls", lambda: True)

    task_token = current_llm_task_var.set("generate_reasoning")
    log_token = llm_call_log_var.set([])
    try:
        await gateway.chat(
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.0,
            model="gpt-5.2",
        )
        records = list(llm_call_log_var.get() or [])
    finally:
        llm_call_log_var.reset(log_token)
        current_llm_task_var.reset(task_token)

    assert len(records) == 1
    assert records[0]["task"] == "generate_reasoning"
    assert records[0]["model"] == "gpt-5.2"
    assert records[0]["attempt"] == 1
    assert records[0]["is_fallback"] is False
    assert records[0]["status"] == "success"
    assert records[0]["error_type"] is None
    assert records[0]["duration_seconds"] >= 0


@pytest.mark.asyncio
async def test_chat_records_primary_failure_before_fallback_success(monkeypatch):
    async def fake_create(**kwargs):
        if kwargs["model"] == "gpt-5.2":
            raise RuntimeError("primary unavailable")
        return _successful_response(kwargs["model"])

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")
    monkeypatch.setattr("app.services.archi_config.get_debug_llm_calls", lambda: True)

    task_token = current_llm_task_var.set("generate")
    log_token = llm_call_log_var.set([])
    try:
        result = await gateway.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5.2",
        )
        records = list(llm_call_log_var.get() or [])
    finally:
        llm_call_log_var.reset(log_token)
        current_llm_task_var.reset(task_token)

    assert result.model == "gpt-4o-mini"
    assert [(row["attempt"], row["is_fallback"], row["status"]) for row in records] == [
        (1, False, "error"),
        (2, True, "success"),
    ]
    assert records[0]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_chat_records_timeout_and_preserves_exception(monkeypatch):
    async def fake_create(**kwargs):
        raise TimeoutError(f'{kwargs["model"]} timed out')

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")
    monkeypatch.setattr("app.services.archi_config.get_debug_llm_calls", lambda: True)

    task_token = current_llm_task_var.set("normalizer")
    log_token = llm_call_log_var.set([])
    try:
        with pytest.raises(TimeoutError, match="gpt-4o-mini timed out"):
            await gateway.chat(
                messages=[{"role": "user", "content": "hello"}],
                model="gpt-5.2",
            )
        records = list(llm_call_log_var.get() or [])
    finally:
        llm_call_log_var.reset(log_token)
        current_llm_task_var.reset(task_token)

    assert len(records) == 2
    assert [row["status"] for row in records] == ["timeout", "timeout"]
    assert [row["attempt"] for row in records] == [1, 2]
    assert all(row["error_type"] == "TimeoutError" for row in records)


@pytest.mark.asyncio
async def test_chat_uses_request_hash_for_redis_cache(monkeypatch):
    calls: dict[str, object] = {}

    async def fake_create(**kwargs):
        calls["create_kwargs"] = kwargs
        return SimpleNamespace(
            id="resp-1",
            model=kwargs["model"],
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
        )

    gateway = _build_gateway(fake_create)

    async def fake_get_cached(key):
        calls["cache_get_key"] = key
        return None

    async def fake_set_cached(key, response):
        calls["cache_set_key"] = key
        calls["cached_response"] = response

    gateway._get_cached = fake_get_cached
    gateway._set_cached = fake_set_cached

    monkeypatch.setattr("app.services.llm_gateway.get_llm_model", lambda: "gpt-5.2")
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")

    messages = [{"role": "user", "content": "What is VPS pricing?"}]
    result = await gateway.chat(messages=messages, temperature=0.0, model="gpt-5.2")

    expected_key = _cache_key(
        messages,
        "gpt-5.2",
        0.0,
        {"response_format": None, "max_tokens": 256},
    )
    assert calls["cache_get_key"] == expected_key
    assert calls["cache_set_key"] == expected_key
    assert calls["create_kwargs"]["prompt_cache_key"] == "shared-prompt-cache-key"
    assert calls["create_kwargs"]["prompt_cache_retention"] == "in_memory"
    assert "max_completion_tokens" in calls["create_kwargs"]
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_chat_requests_json_response_for_structured_task(monkeypatch):
    calls: dict[str, object] = {}

    async def fake_create(**kwargs):
        calls["create_kwargs"] = kwargs
        return _successful_response(kwargs["model"])

    gateway = _build_gateway(fake_create)

    async def fake_get_cached(key):
        calls["cache_get_key"] = key
        return None

    async def fake_set_cached(key, response):
        calls["cache_set_key"] = key

    gateway._get_cached = fake_get_cached
    gateway._set_cached = fake_set_cached
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")

    token = current_llm_task_var.set("normalizer")
    messages = [
        {"role": "system", "content": "只返回 JSON。"},
        {"role": "user", "content": "测试"},
    ]
    try:
        await gateway.chat(messages=messages, temperature=0.0, model="gpt-5.2")
    finally:
        current_llm_task_var.reset(token)

    assert calls["create_kwargs"]["response_format"] == {"type": "json_object"}
    expected_key = _cache_key(
        messages,
        "gpt-5.2",
        0.0,
        {"response_format": {"type": "json_object"}, "max_tokens": 256},
    )
    assert calls["cache_get_key"] == expected_key
    assert calls["cache_set_key"] == expected_key


@pytest.mark.asyncio
async def test_chat_preserves_explicit_response_format(monkeypatch):
    calls: dict[str, object] = {}
    explicit = {"type": "text"}

    async def fake_create(**kwargs):
        calls["create_kwargs"] = kwargs
        return _successful_response(kwargs["model"])

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")

    token = current_llm_task_var.set("normalizer")
    try:
        await gateway.chat(
            messages=[{"role": "user", "content": "测试"}],
            model="gpt-5.2",
            response_format=explicit,
        )
    finally:
        current_llm_task_var.reset(token)

    assert calls["create_kwargs"]["response_format"] is explicit


@pytest.mark.asyncio
async def test_chat_retries_without_response_format_when_provider_rejects_it(monkeypatch):
    calls: list[dict[str, object]] = []

    async def fake_create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ValueError("unknown parameter: response_format")
        return _successful_response(kwargs["model"])

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")

    token = current_llm_task_var.set("normalizer")
    try:
        result = await gateway.chat(
            messages=[
                {"role": "system", "content": "只返回 JSON。"},
                {"role": "user", "content": "测试"},
            ],
            model="gpt-5.2",
        )
    finally:
        current_llm_task_var.reset(token)

    assert result.content == "ok"
    assert calls[0]["model"] == "gpt-5.2"
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[1]["model"] == "gpt-5.2"
    assert "response_format" not in calls[1]


@pytest.mark.asyncio
async def test_chat_returns_cached_response_without_calling_provider(monkeypatch):
    async def fake_create(**kwargs):
        raise AssertionError("provider should not be called on cache hit")

    gateway = _build_gateway(fake_create)
    cached = LLMResponse(
        content="cached-value",
        model="gpt-5.2",
        provider="openai",
        input_tokens=1,
        output_tokens=1,
    )

    async def fake_get_cached(key):
        return cached

    async def fake_set_cached(key, response):
        raise AssertionError("cache set should not run on cache hit")

    gateway._get_cached = fake_get_cached
    gateway._set_cached = fake_set_cached

    monkeypatch.setattr("app.services.llm_gateway.get_llm_model", lambda: "gpt-5.2")
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")

    result = await gateway.chat(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.1,
        model="gpt-5.2",
    )
    assert result is cached


@pytest.mark.asyncio
async def test_clear_llm_cache_deletes_llm_namespace(monkeypatch):
    class FakeRedis:
        def __init__(self) -> None:
            self.closed = False

        async def keys(self, pattern):
            assert pattern == "llm_cache:*"
            return [b"llm_cache:a", b"llm_cache:b", b"llm_cache:c"]

        async def delete(self, *keys):
            assert keys == (b"llm_cache:a", b"llm_cache:b", b"llm_cache:c")
            return 3

        async def close(self):
            self.closed = True

    fake_redis = FakeRedis()
    monkeypatch.setattr("app.services.llm_gateway.get_settings", lambda: _Settings())

    from unittest.mock import patch

    with patch("redis.asyncio.from_url", return_value=fake_redis):
        result = await clear_llm_cache()

    assert result == {"deleted_keys": 3}
    assert fake_redis.closed is True


@pytest.mark.asyncio
async def test_cached_empty_content_is_purged_and_returns_none(monkeypatch):
    """_get_cached() should delete stale empty-content entries and return None."""
    import pickle

    empty_cached = LLMResponse(
        content="",
        model="gpt-5.2",
        provider="openai",
        input_tokens=1,
        output_tokens=0,
    )

    class FakeRedis:
        def __init__(self):
            self.deleted_keys: list[str] = []
            self.closed = False

        async def get(self, key):
            return pickle.dumps(empty_cached)

        async def delete(self, key):
            self.deleted_keys.append(key)

        async def close(self):
            self.closed = True

    fake_redis = FakeRedis()
    gateway = OpenAIGateway.__new__(OpenAIGateway)
    gateway._settings = _Settings()

    from unittest.mock import patch

    with patch("redis.asyncio.from_url", return_value=fake_redis):
        result = await gateway._get_cached("test-key")

    assert result is None
    assert len(fake_redis.deleted_keys) == 1
    assert fake_redis.closed is True


@pytest.mark.asyncio
async def test_empty_content_primary_triggers_fallback(monkeypatch):
    """When primary model returns empty content, chat() should fall back to secondary."""

    call_log: list[str] = []

    async def fake_create(**kwargs):
        model = kwargs["model"]
        call_log.append(model)
        if model == "gpt-5.2":
            # Primary returns empty content
            return SimpleNamespace(
                id="resp-empty",
                model=model,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=""),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=0),
            )
        # Fallback returns valid content
        return _successful_response(model)

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")

    result = await gateway.chat(
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-5.2",
    )

    assert call_log == ["gpt-5.2", "gpt-4o-mini"]
    assert result.content == "ok"
    assert result.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_set_cached_rejects_empty_content(monkeypatch):
    """_set_cached() should skip caching when content is empty."""
    set_calls: list[str] = []

    class FakeRedis:
        async def setex(self, key, ttl, value):
            set_calls.append(key)

        async def close(self):
            pass

    fake_redis = FakeRedis()
    gateway = OpenAIGateway.__new__(OpenAIGateway)
    gateway._settings = _Settings()

    from unittest.mock import patch

    empty_response = LLMResponse(
        content="",
        model="gpt-5.2",
        provider="openai",
        input_tokens=1,
        output_tokens=0,
    )
    with patch("redis.asyncio.from_url", return_value=fake_redis):
        await gateway._set_cached("test-key", empty_response)

    assert set_calls == [], "empty content should not be cached"

    valid_response = LLMResponse(
        content="valid",
        model="gpt-5.2",
        provider="openai",
        input_tokens=1,
        output_tokens=1,
    )
    with patch("redis.asyncio.from_url", return_value=fake_redis):
        await gateway._set_cached("test-key", valid_response)

    assert len(set_calls) == 1


# ---------------------------------------------------------------------------
# Issue 02: Lightweight telemetry (always-on, no prompt/response)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_records_lightweight_telemetry_without_debug_flag(monkeypatch):
    """Lightweight LLM telemetry must be captured even when debug_llm_calls is False."""
    async def fake_create(**kwargs):
        return _successful_response(kwargs["model"])

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")
    monkeypatch.setattr("app.services.archi_config.get_debug_llm_calls", lambda: False)

    task_token = current_llm_task_var.set("normalizer")
    log_token = llm_call_log_var.set([])
    try:
        await gateway.chat(
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.0,
            model="gpt-5.2",
        )
        records = list(llm_call_log_var.get() or [])
    finally:
        llm_call_log_var.reset(log_token)
        current_llm_task_var.reset(task_token)

    assert len(records) == 1
    rec = records[0]
    # Lightweight fields present
    assert rec["task"] == "normalizer"
    assert rec["model"] == "gpt-5.2"
    assert rec["attempt"] == 1
    assert rec["status"] == "success"
    assert rec["duration_seconds"] >= 0
    # Heavy fields NOT present
    assert "messages" not in rec
    assert "response_content" not in rec
    assert "input_tokens" not in rec
    assert "output_tokens" not in rec
    assert "cost_usd" not in rec


@pytest.mark.asyncio
async def test_chat_records_429_as_rate_limited_status(monkeypatch):
    """429 errors must be recorded with status='rate_limited'."""
    import httpx

    async def fake_create(**kwargs):
        # Simulate a 429 response
        response = httpx.Response(
            status_code=429,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            json={"error": {"message": "Too many requests", "type": "rate_limit_error"}},
        )
        raise openai.RateLimitError(
            message="Too many requests",
            response=response,
            body={"error": {"message": "Too many requests", "type": "rate_limit_error"}},
        )

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")
    monkeypatch.setattr("app.services.archi_config.get_debug_llm_calls", lambda: False)
    # Disable backoff retries to keep test fast
    monkeypatch.setattr("app.services.llm_gateway._429_MAX_RETRIES", 0)

    task_token = current_llm_task_var.set("generate")
    log_token = llm_call_log_var.set([])
    try:
        with pytest.raises(openai.RateLimitError):
            await gateway.chat(
                messages=[{"role": "user", "content": "hello"}],
                model="gpt-5.2",
            )
        records = list(llm_call_log_var.get() or [])
    finally:
        llm_call_log_var.reset(log_token)
        current_llm_task_var.reset(task_token)

    assert len(records) == 2  # primary + fallback both 429
    assert all(r["status"] == "rate_limited" for r in records)
    assert all(r["error_type"] == "RateLimitError" for r in records)


@pytest.mark.asyncio
async def test_429_backoff_recovery_records_telemetry(monkeypatch):
    """429 backoff recovery must record backoff_attempt and wait_seconds."""
    import asyncio as _asyncio

    call_count = {"n": 0}
    sleep_calls: list[float] = []

    async def fake_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: 429
            response = httpx.Response(
                status_code=429,
                request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
                json={"error": {"message": "Too many requests", "type": "rate_limit_error"}},
            )
            raise openai.RateLimitError(
                message="Too many requests", response=response,
                body={"error": {"message": "Too many requests", "type": "rate_limit_error"}},
            )
        # Second call: success
        return _successful_response(kwargs["model"])

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")
    monkeypatch.setattr("app.services.archi_config.get_debug_llm_calls", lambda: False)
    monkeypatch.setattr(_asyncio, "sleep", fake_sleep)

    task_token = current_llm_task_var.set("generate")
    log_token = llm_call_log_var.set([])
    try:
        result = await gateway.chat(messages=[{"role": "user", "content": "hello"}], model="gpt-5.2")
        records = list(llm_call_log_var.get() or [])
    finally:
        llm_call_log_var.reset(log_token)
        current_llm_task_var.reset(task_token)

    assert result.content == "ok"
    assert len(sleep_calls) == 1  # one backoff sleep
    assert sleep_calls[0] == 2.0  # base delay
    # Find the success_after_429 record
    recovery = [r for r in records if r["status"] == "success_after_429"]
    assert len(recovery) == 1
    assert recovery[0]["backoff_attempt"] == 1
    assert recovery[0]["wait_seconds"] == 2.0


@pytest.mark.asyncio
async def test_429_backoff_exhaustion_falls_back_to_next_model(monkeypatch):
    """Consecutive 429s exhaust retries, then fall back to next model."""
    import asyncio as _asyncio

    sleep_calls: list[float] = []
    models_called: list[str] = []

    async def fake_create(**kwargs):
        models_called.append(kwargs["model"])
        response = httpx.Response(
            status_code=429,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            json={"error": {"message": "Too many requests", "type": "rate_limit_error"}},
        )
        raise openai.RateLimitError(
            message="Too many requests", response=response,
            body={"error": {"message": "Too many requests", "type": "rate_limit_error"}},
        )

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")
    monkeypatch.setattr("app.services.archi_config.get_debug_llm_calls", lambda: False)
    monkeypatch.setattr(_asyncio, "sleep", fake_sleep)

    task_token = current_llm_task_var.set("generate")
    log_token = llm_call_log_var.set([])
    try:
        with pytest.raises(openai.RateLimitError):
            await gateway.chat(messages=[{"role": "user", "content": "hello"}], model="gpt-5.2")
        records = list(llm_call_log_var.get() or [])
    finally:
        llm_call_log_var.reset(log_token)
        current_llm_task_var.reset(task_token)

    # primary: 1 initial + 2 backoff = 3 calls; fallback: 1 initial + 2 backoff = 3 calls
    assert len(models_called) == 6
    assert models_called[:3] == ["gpt-5.2"] * 3
    assert models_called[3:] == ["gpt-4o-mini"] * 3
    # 4 backoff sleeps total (2 per model)
    assert len(sleep_calls) == 4
    # Exponential: 2.0, 4.0 for primary; 2.0, 4.0 for fallback
    assert sleep_calls == [2.0, 4.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_429_backoff_respects_retry_after_header(monkeypatch):
    """Retry-After header must be used as backoff delay."""
    import asyncio as _asyncio

    sleep_calls: list[float] = []
    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            response = httpx.Response(
                status_code=429,
                request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
                headers={"retry-after": "15"},
                json={"error": {"message": "Too many requests", "type": "rate_limit_error"}},
            )
            raise openai.RateLimitError(
                message="Too many requests", response=response,
                body={"error": {"message": "Too many requests", "type": "rate_limit_error"}},
            )
        return _successful_response(kwargs["model"])

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")
    monkeypatch.setattr("app.services.archi_config.get_debug_llm_calls", lambda: False)
    monkeypatch.setattr(_asyncio, "sleep", fake_sleep)

    task_token = current_llm_task_var.set("generate")
    log_token = llm_call_log_var.set([])
    try:
        result = await gateway.chat(messages=[{"role": "user", "content": "hello"}], model="gpt-5.2")
        records = list(llm_call_log_var.get() or [])
    finally:
        llm_call_log_var.reset(log_token)
        current_llm_task_var.reset(task_token)

    assert result.content == "ok"
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 15.0  # Retry-After value used
    recovery = [r for r in records if r["status"] == "success_after_429"]
    assert recovery[0]["wait_seconds"] == 15.0


@pytest.mark.asyncio
async def test_429_backoff_delay_capped_at_max(monkeypatch):
    """Backoff delay must not exceed _429_MAX_DELAY."""
    import asyncio as _asyncio

    sleep_calls: list[float] = []
    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            response = httpx.Response(
                status_code=429,
                request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
                headers={"retry-after": "999"},  # way above max
                json={"error": {"message": "Too many requests", "type": "rate_limit_error"}},
            )
            raise openai.RateLimitError(
                message="Too many requests", response=response,
                body={"error": {"message": "Too many requests", "type": "rate_limit_error"}},
            )
        return _successful_response(kwargs["model"])

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")
    monkeypatch.setattr("app.services.archi_config.get_debug_llm_calls", lambda: False)
    monkeypatch.setattr(_asyncio, "sleep", fake_sleep)

    task_token = current_llm_task_var.set("generate")
    log_token = llm_call_log_var.set([])
    try:
        result = await gateway.chat(messages=[{"role": "user", "content": "hello"}], model="gpt-5.2")
        records = list(llm_call_log_var.get() or [])
    finally:
        llm_call_log_var.reset(log_token)
        current_llm_task_var.reset(task_token)

    assert result.content == "ok"
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 60.0  # capped at _429_MAX_DELAY
    recovery = [r for r in records if r["status"] == "success_after_429"]
    assert recovery[0]["wait_seconds"] == 60.0


@pytest.mark.asyncio
async def test_lightweight_records_fallback_status(monkeypatch):
    """Lightweight telemetry must track fallback attempts."""
    async def fake_create(**kwargs):
        if kwargs["model"] == "gpt-5.2":
            raise RuntimeError("primary down")
        return _successful_response(kwargs["model"])

    gateway = _build_gateway(fake_create)
    await _disable_gateway_cache(gateway)
    monkeypatch.setattr("app.services.llm_gateway.get_llm_fallback_model", lambda: "gpt-4o-mini")
    monkeypatch.setattr("app.services.archi_config.get_debug_llm_calls", lambda: False)

    task_token = current_llm_task_var.set("evidence_quality")
    log_token = llm_call_log_var.set([])
    try:
        result = await gateway.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5.2",
        )
        records = list(llm_call_log_var.get() or [])
    finally:
        llm_call_log_var.reset(log_token)
        current_llm_task_var.reset(task_token)

    assert result.model == "gpt-4o-mini"
    assert len(records) == 2
    assert records[0]["status"] == "error"
    assert records[0]["is_fallback"] is False
    assert records[1]["status"] == "success"
    assert records[1]["is_fallback"] is True
