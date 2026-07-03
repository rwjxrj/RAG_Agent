import pytest
from types import SimpleNamespace
import httpx
from openai import APIConnectionError, APITimeoutError

from app.search import embeddings


class _FakeEmbeddingItem:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding


class _FakeEmbeddingResponse:
    def __init__(self) -> None:
        self.data = [_FakeEmbeddingItem([0.1, 0.2, 0.3])]


class _FakeOpenAIEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeEmbeddingResponse()


class _FakeOpenAIClient:
    created_kwargs: dict | None = None
    last_instance: "_FakeOpenAIClient | None" = None

    def __init__(self, **kwargs) -> None:
        type(self).created_kwargs = kwargs
        type(self).last_instance = self
        self.embeddings = _FakeOpenAIEmbeddings()


class _StatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _SequencedEmbeddings:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _configure_openai_provider(monkeypatch, provider_name: str = "aliyun") -> None:
    monkeypatch.setattr(embeddings, "get_embedding_provider_name", lambda: provider_name)
    monkeypatch.setattr(embeddings, "get_embedding_model", lambda: "text-embedding-v4")
    monkeypatch.setattr(embeddings, "get_embedding_dimensions", lambda: 1024)
    monkeypatch.setattr(embeddings, "get_embedding_api_key", lambda: "embedding-key")
    monkeypatch.setattr(
        embeddings,
        "get_embedding_base_url",
        lambda: "https://embedding.example.com/v1",
    )
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_request_timeout_seconds=60.0,
            embedding_retry_attempts=3,
            embedding_retry_backoff_seconds=1.0,
        ),
        raising=False,
    )
    monkeypatch.setattr(embeddings, "AsyncOpenAI", _FakeOpenAIClient)


@pytest.mark.asyncio
async def test_openai_embedding_provider_uses_embedding_specific_config(monkeypatch):
    _configure_openai_provider(monkeypatch, "openai")
    monkeypatch.setattr(embeddings, "get_embedding_model", lambda: "text-embedding-3-small")

    provider = embeddings.OpenAIEmbeddingProvider()
    vectors = await provider.embed(["hello"])

    assert vectors == [[0.1, 0.2, 0.3]]
    assert _FakeOpenAIClient.created_kwargs == {
        "api_key": "embedding-key",
        "base_url": "https://embedding.example.com/v1",
        "max_retries": 0,
        "timeout": 60.0,
    }
    assert _FakeOpenAIClient.last_instance is not None
    assert _FakeOpenAIClient.last_instance.embeddings.calls == [
        {"model": "text-embedding-3-small", "input": ["hello"]}
    ]


@pytest.mark.asyncio
async def test_aliyun_embedding_provider_passes_configured_dimensions(monkeypatch):
    _configure_openai_provider(monkeypatch)

    provider = embeddings.get_embedding_provider()
    vectors = await provider.embed(["你好"])

    assert vectors == [[0.1, 0.2, 0.3]]
    assert isinstance(provider, embeddings.OpenAIEmbeddingProvider)
    assert provider.max_batch_size() == 10
    assert _FakeOpenAIClient.last_instance is not None
    assert _FakeOpenAIClient.last_instance.embeddings.calls == [
        {"model": "text-embedding-v4", "input": ["你好"], "dimensions": 1024}
    ]


def test_non_aliyun_openai_provider_has_no_batch_limit(monkeypatch):
    _configure_openai_provider(monkeypatch, "openai")

    provider = embeddings.OpenAIEmbeddingProvider()

    assert provider.max_batch_size() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [408, 409, 429, 500, 503])
async def test_embedding_provider_retries_transient_http_errors(monkeypatch, status_code):
    _configure_openai_provider(monkeypatch)
    sleeps: list[float] = []
    monkeypatch.setattr(
        embeddings,
        "asyncio",
        SimpleNamespace(sleep=lambda delay: _record_sleep(sleeps, delay)),
        raising=False,
    )
    provider = embeddings.OpenAIEmbeddingProvider()
    sequenced = _SequencedEmbeddings([
        _StatusError(status_code),
        _StatusError(status_code),
        _FakeEmbeddingResponse(),
    ])
    provider._client.embeddings = sequenced

    vectors = await provider.embed(["hello"])

    assert vectors == [[0.1, 0.2, 0.3]]
    assert len(sequenced.calls) == 3
    assert sleeps == [1.0, 2.0]


async def _record_sleep(sleeps: list[float], delay: float) -> None:
    sleeps.append(delay)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
async def test_embedding_provider_does_not_retry_permanent_http_errors(monkeypatch, status_code):
    _configure_openai_provider(monkeypatch)
    provider = embeddings.OpenAIEmbeddingProvider()
    sequenced = _SequencedEmbeddings([_StatusError(status_code)])
    provider._client.embeddings = sequenced

    with pytest.raises(_StatusError):
        await provider.embed(["hello"])

    assert len(sequenced.calls) == 1


@pytest.mark.asyncio
async def test_embedding_provider_raises_after_retry_exhaustion(monkeypatch):
    _configure_openai_provider(monkeypatch)
    monkeypatch.setattr(
        embeddings,
        "asyncio",
        SimpleNamespace(sleep=lambda delay: _record_sleep([], delay)),
        raising=False,
    )
    provider = embeddings.OpenAIEmbeddingProvider()
    sequenced = _SequencedEmbeddings([_StatusError(429), _StatusError(429), _StatusError(429)])
    provider._client.embeddings = sequenced

    with pytest.raises(_StatusError, match="HTTP 429"):
        await provider.embed(["hello"])

    assert len(sequenced.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "connection_error",
    [
        APIConnectionError(request=httpx.Request("POST", "https://embedding.example.com/v1/embeddings")),
        APITimeoutError(request=httpx.Request("POST", "https://embedding.example.com/v1/embeddings")),
    ],
)
async def test_embedding_provider_retries_openai_connection_errors(monkeypatch, connection_error):
    _configure_openai_provider(monkeypatch)
    monkeypatch.setattr(
        embeddings,
        "asyncio",
        SimpleNamespace(sleep=lambda delay: _record_sleep([], delay)),
    )
    provider = embeddings.OpenAIEmbeddingProvider()
    sequenced = _SequencedEmbeddings([connection_error, _FakeEmbeddingResponse()])
    provider._client.embeddings = sequenced

    vectors = await provider.embed(["hello"])

    assert vectors == [[0.1, 0.2, 0.3]]
    assert len(sequenced.calls) == 2


@pytest.mark.asyncio
async def test_ollama_embedding_provider_calls_local_embeddings_api(monkeypatch):
    requests: list[dict] = []

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"embedding": [0.4, 0.5, 0.6]}

    class _FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            requests.append({"client_kwargs": kwargs})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, json: dict):
            requests.append({"url": url, "json": json})
            return _FakeResponse()

    monkeypatch.setattr(embeddings, "get_embedding_provider_name", lambda: "ollama")
    monkeypatch.setattr(embeddings, "get_embedding_model", lambda: "nomic-embed-text")
    monkeypatch.setattr(embeddings, "get_embedding_dimensions", lambda: 768)
    monkeypatch.setattr(embeddings, "get_embedding_base_url", lambda: "http://host.docker.internal:11434")
    monkeypatch.setattr(embeddings.httpx, "AsyncClient", _FakeAsyncClient)

    provider = embeddings.get_embedding_provider()
    vectors = await provider.embed(["hello"])

    assert vectors == [[0.4, 0.5, 0.6]]
    assert provider.dimensions() == 768
    assert requests == [
        {"client_kwargs": {"timeout": 30.0}},
        {
            "url": "http://host.docker.internal:11434/api/embeddings",
            "json": {"model": "nomic-embed-text", "prompt": "hello"},
        },
    ]
