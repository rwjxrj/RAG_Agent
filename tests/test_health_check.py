import pytest

from app.services import embedding_config, health_check


class _FakeEmbeddingItem:
    def __init__(self, dimensions: int) -> None:
        self.embedding = [0.1] * dimensions


class _FakeEmbeddingResponse:
    def __init__(self, dimensions: int) -> None:
        self.data = [_FakeEmbeddingItem(dimensions)]


class _FakeEmbeddings:
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeEmbeddingResponse(self.dimensions)


class _FakeOpenAI:
    response_dimensions = 1024
    last_instance: "_FakeOpenAI | None" = None

    def __init__(self, **kwargs) -> None:
        type(self).last_instance = self
        self.embeddings = _FakeEmbeddings(type(self).response_dimensions)


def _configure_aliyun(monkeypatch, dimensions: int = 1024) -> None:
    monkeypatch.setattr(embedding_config, "get_embedding_provider_name", lambda: "aliyun")
    monkeypatch.setattr(embedding_config, "get_embedding_model", lambda: "text-embedding-v4")
    monkeypatch.setattr(embedding_config, "get_embedding_dimensions", lambda: dimensions)
    monkeypatch.setattr(embedding_config, "get_embedding_api_key", lambda: "dashscope-key")
    monkeypatch.setattr(
        embedding_config,
        "get_embedding_base_url",
        lambda: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr("openai.AsyncOpenAI", _FakeOpenAI)


@pytest.mark.asyncio
async def test_aliyun_embedding_health_check_passes_dimensions(monkeypatch):
    _FakeOpenAI.response_dimensions = 1024
    _configure_aliyun(monkeypatch)

    result = await health_check._check_embedding()

    assert result == "text-embedding-v4 (1024d) via aliyun"
    assert _FakeOpenAI.last_instance is not None
    assert _FakeOpenAI.last_instance.embeddings.calls == [
        {"model": "text-embedding-v4", "input": ["test"], "dimensions": 1024}
    ]


@pytest.mark.asyncio
async def test_aliyun_embedding_health_check_rejects_dimension_mismatch(monkeypatch):
    _FakeOpenAI.response_dimensions = 768
    _configure_aliyun(monkeypatch, dimensions=1024)

    with pytest.raises(ValueError, match="向量维度不一致.*期望 1024.*实际 768"):
        await health_check._check_embedding()


@pytest.mark.asyncio
async def test_embedding_dimension_mismatch_is_visible_in_health_result(monkeypatch):
    _FakeOpenAI.response_dimensions = 768
    _configure_aliyun(monkeypatch, dimensions=1024)

    result = await health_check._timed_check("Embedding 模型", health_check._check_embedding())

    assert result["status"] == "error"
    assert result["detail"] == "向量维度不一致：期望 1024，实际 768"
