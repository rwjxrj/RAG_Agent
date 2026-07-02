import pytest

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


@pytest.mark.asyncio
async def test_openai_embedding_provider_uses_embedding_specific_config(monkeypatch):
    monkeypatch.setattr(embeddings, "get_embedding_provider_name", lambda: "openai")
    monkeypatch.setattr(
        embeddings,
        "get_embedding_model",
        lambda: "text-embedding-3-small",
    )
    monkeypatch.setattr(embeddings, "get_embedding_dimensions", lambda: 1536)
    monkeypatch.setattr(embeddings, "get_embedding_api_key", lambda: "embedding-key")
    monkeypatch.setattr(embeddings, "get_embedding_base_url", lambda: "https://embedding.example.com/v1")
    monkeypatch.setattr(embeddings, "AsyncOpenAI", _FakeOpenAIClient)

    provider = embeddings.OpenAIEmbeddingProvider()
    vectors = await provider.embed(["hello"])

    assert vectors == [[0.1, 0.2, 0.3]]
    assert _FakeOpenAIClient.created_kwargs == {
        "api_key": "embedding-key",
        "base_url": "https://embedding.example.com/v1",
    }
    assert _FakeOpenAIClient.last_instance is not None
    assert _FakeOpenAIClient.last_instance.embeddings.calls == [
        {"model": "text-embedding-3-small", "input": ["hello"]}
    ]


@pytest.mark.asyncio
async def test_aliyun_embedding_provider_passes_configured_dimensions(monkeypatch):
    monkeypatch.setattr(embeddings, "get_embedding_provider_name", lambda: "aliyun")
    monkeypatch.setattr(embeddings, "get_embedding_model", lambda: "text-embedding-v4")
    monkeypatch.setattr(embeddings, "get_embedding_dimensions", lambda: 1024)
    monkeypatch.setattr(embeddings, "get_embedding_api_key", lambda: "dashscope-key")
    monkeypatch.setattr(
        embeddings,
        "get_embedding_base_url",
        lambda: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr(embeddings, "AsyncOpenAI", _FakeOpenAIClient)

    provider = embeddings.get_embedding_provider()
    vectors = await provider.embed(["你好"])

    assert vectors == [[0.1, 0.2, 0.3]]
    assert isinstance(provider, embeddings.OpenAIEmbeddingProvider)
    assert _FakeOpenAIClient.last_instance is not None
    assert _FakeOpenAIClient.last_instance.embeddings.calls == [
        {"model": "text-embedding-v4", "input": ["你好"], "dimensions": 1024}
    ]


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
