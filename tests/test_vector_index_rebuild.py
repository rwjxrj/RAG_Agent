from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from app.api.schemas import VectorIndexStatusResponse
from app.main import create_app
from app.search.qdrant_client import QdrantSearchClient
from app.services.vector_index_rebuild import (
    VectorIndexConflictError,
    VectorIndexMaintenanceError,
    VectorIndexStatus,
    ensure_vector_index_ready,
    get_vector_index_status,
    mark_vector_index_rebuild_required,
    save_vector_index_status,
    queue_vector_index_rebuild,
    sanitize_rebuild_error,
    build_embedding_fingerprint,
    rebuild_vector_index,
    vector_space_changed,
)


def test_embedding_fingerprint_ignores_api_key_and_normalizes_base_url():
    first = build_embedding_fingerprint(
        provider="custom",
        model="embed-v1",
        dimensions=1024,
        base_url="https://embedding.example.com/v1/",
        api_key="old-secret",
    )
    second = build_embedding_fingerprint(
        provider=" custom ",
        model=" embed-v1 ",
        dimensions=1024,
        base_url="https://embedding.example.com/v1",
        api_key="new-secret",
    )

    assert first == second


def test_embedding_fingerprint_changes_when_vector_space_changes():
    original = build_embedding_fingerprint("openai", "embed-v1", 1536, "https://api.example.com/v1", "key")

    assert original != build_embedding_fingerprint("ollama", "embed-v1", 1536, "https://api.example.com/v1", "key")
    assert original != build_embedding_fingerprint("openai", "embed-v2", 1536, "https://api.example.com/v1", "key")
    assert original != build_embedding_fingerprint("openai", "embed-v1", 768, "https://api.example.com/v1", "key")
    assert original != build_embedding_fingerprint("openai", "embed-v1", 1536, "https://other.example.com/v1", "key")


class _FakeEmbedder:
    def __init__(self, dimensions: int = 3, *, fail: bool = False):
        self._dimensions = dimensions
        self._fail = fail
        self.calls: list[list[str]] = []

    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self._fail:
            raise RuntimeError("provider unavailable")
        return [[float(i + 1)] * self._dimensions for i, _ in enumerate(texts)]


class _FakeQdrant:
    def __init__(self):
        self.recreated_with: int | None = None
        self.batches: list[list[dict]] = []

    def recreate_collection(self, dimensions: int) -> None:
        self.recreated_with = dimensions

    def upsert_chunks(self, chunks: list[dict]) -> None:
        self.batches.append(chunks)


@pytest.mark.asyncio
async def test_rebuild_vector_index_probes_before_recreating_and_reports_progress():
    embedder = _FakeEmbedder()
    qdrant = _FakeQdrant()
    chunks = [
        SimpleNamespace(
            id="chunk-1",
            chunk_text="first",
            document_id="doc-1",
            chunk_metadata={"page_kind": "faq"},
            document=SimpleNamespace(source_url="https://example.com/1", doc_type="faq"),
        ),
        SimpleNamespace(
            id="chunk-2",
            chunk_text="second",
            document_id="doc-2",
            chunk_metadata=None,
            document=SimpleNamespace(source_url="https://example.com/2", doc_type="docs"),
        ),
    ]
    progress: list[tuple[int, int]] = []

    result = await rebuild_vector_index(
        chunks=chunks,
        embedder=embedder,
        qdrant=qdrant,
        batch_size=1,
        on_progress=lambda done, total: progress.append((done, total)),
    )

    assert result == 2
    assert embedder.calls[0] == ["vector index readiness probe"]
    assert qdrant.recreated_with == 3
    assert progress == [(1, 2), (2, 2)]
    assert qdrant.batches[0][0]["chunk_id"] == "chunk-1"
    assert qdrant.batches[0][0]["metadata"] == {"page_kind": "faq"}


@pytest.mark.asyncio
async def test_rebuild_vector_index_does_not_delete_collection_when_probe_fails():
    embedder = _FakeEmbedder(fail=True)
    qdrant = _FakeQdrant()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await rebuild_vector_index(chunks=[], embedder=embedder, qdrant=qdrant)

    assert qdrant.recreated_with is None


@pytest.mark.asyncio
async def test_rebuild_vector_index_rejects_dimension_mismatch_before_recreating():
    class _WrongDimensionEmbedder(_FakeEmbedder):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.1, 0.2]]

    qdrant = _FakeQdrant()

    with pytest.raises(ValueError, match="configured dimensions 3"):
        await rebuild_vector_index(chunks=[], embedder=_WrongDimensionEmbedder(), qdrant=qdrant)

    assert qdrant.recreated_with is None


def test_vector_index_status_requires_maintenance_when_not_ready():
    assert VectorIndexStatus(status="ready").is_ready is True
    assert VectorIndexStatus(status="required").is_ready is False
    assert VectorIndexStatus(status="failed", error="boom").is_ready is False


def test_vector_index_status_round_trips_json():
    status = VectorIndexStatus(
        status="running",
        job_id="job-1",
        processed_chunks=10,
        total_chunks=20,
        error=None,
        indexed_fingerprint="fingerprint",
    )

    restored = VectorIndexStatus.from_json(status.to_json())

    assert restored.status == "running"
    assert restored.job_id == "job-1"
    assert restored.processed_chunks == 10
    assert restored.total_chunks == 20
    assert restored.indexed_fingerprint == "fingerprint"


def test_vector_space_changed_ignores_api_key_only_change():
    before = {
        "embedding_provider": "openai",
        "embedding_model": "embed-v1",
        "embedding_dimensions": 1536,
        "embedding_base_url": "https://api.example.com/v1",
        "embedding_api_key": "old",
    }
    after = {**before, "embedding_api_key": "new"}

    assert vector_space_changed(before, after) is False
    assert vector_space_changed(before, {**after, "embedding_model": "embed-v2"}) is True


def test_vector_index_status_response_exposes_progress():
    response = VectorIndexStatusResponse(
        status="running",
        job_id="job-1",
        processed_chunks=4,
        total_chunks=10,
        error=None,
        updated_at=None,
    )

    assert response.status == "running"
    assert response.processed_chunks == 4


def test_app_registers_vector_index_maintenance_handler():
    app = create_app()

    assert VectorIndexMaintenanceError in app.exception_handlers


class _FakeScalarOneResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeStateSession:
    def __init__(self, row=None):
        self.row = row
        self.added = []

    async def execute(self, _statement, _params=None):
        return _FakeScalarOneResult(self.row)

    def add(self, row):
        self.row = row
        self.added.append(row)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_vector_index_state_defaults_to_ready_when_key_is_absent():
    status = await get_vector_index_status(_FakeStateSession())

    assert status.status == "ready"


@pytest.mark.asyncio
async def test_vector_index_state_is_saved_in_app_config():
    session = _FakeStateSession()

    await save_vector_index_status(
        session,
        VectorIndexStatus(status="required", indexed_fingerprint="old-fingerprint"),
        lock=False,
    )
    restored = await get_vector_index_status(session)

    assert len(session.added) == 1
    assert restored.status == "required"
    assert restored.indexed_fingerprint == "old-fingerprint"


@pytest.mark.asyncio
async def test_vector_index_guard_rejects_required_state():
    row = SimpleNamespace(value=VectorIndexStatus(status="required").to_json())

    with pytest.raises(VectorIndexMaintenanceError):
        await ensure_vector_index_ready(_FakeStateSession(row))


@pytest.mark.asyncio
async def test_queue_vector_index_rebuild_rejects_duplicate_active_job():
    row = SimpleNamespace(value=VectorIndexStatus(
        status="running",
        job_id="job-1",
        updated_at=datetime.now(timezone.utc),
    ).to_json())

    with pytest.raises(VectorIndexConflictError):
        await queue_vector_index_rebuild(_FakeStateSession(row), "job-2", lock=False)


@pytest.mark.asyncio
async def test_stale_queued_job_is_exposed_as_failed():
    stale = VectorIndexStatus(
        status="queued",
        job_id="stale-job",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=11),
    )

    status = await get_vector_index_status(_FakeStateSession(SimpleNamespace(value=stale.to_json())))

    assert status.status == "failed"
    assert status.job_id == "stale-job"
    assert status.error == "向量索引重建任务超过 10 分钟未更新，已停止等待。"


@pytest.mark.asyncio
async def test_stale_active_job_can_be_requeued():
    stale = VectorIndexStatus(
        status="running",
        job_id="stale-job",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=11),
    )
    session = _FakeStateSession(SimpleNamespace(value=stale.to_json()))

    status = await queue_vector_index_rebuild(session, "new-job", lock=False)

    assert status.status == "queued"
    assert status.job_id == "new-job"


@pytest.mark.asyncio
async def test_queue_vector_index_rebuild_sets_queued_state():
    session = _FakeStateSession(
        SimpleNamespace(value=VectorIndexStatus(status="required").to_json())
    )

    status = await queue_vector_index_rebuild(session, "job-2", lock=False)

    assert status.status == "queued"
    assert status.job_id == "job-2"


@pytest.mark.asyncio
async def test_mark_required_preserves_indexed_fingerprint():
    session = _FakeStateSession()

    status = await mark_vector_index_rebuild_required(
        session,
        indexed_fingerprint="old-fingerprint",
        lock=False,
    )

    assert status.status == "required"
    assert status.indexed_fingerprint == "old-fingerprint"


def test_rebuild_error_redacts_known_secrets():
    message = sanitize_rebuild_error(
        RuntimeError("provider rejected api key secret-token-123"),
        secrets=["secret-token-123"],
    )

    assert "secret-token-123" not in message
    assert "[REDACTED]" in message


class _FakeQdrantSdkClient:
    def __init__(self, collection_exists: bool = True):
        self._collection_exists = collection_exists
        self.deleted: list[str] = []
        self.created: list[dict] = []
        self.upserts: list[dict] = []

    def collection_exists(self, collection_name: str) -> bool:
        return self._collection_exists

    def delete_collection(self, collection_name: str) -> None:
        self.deleted.append(collection_name)

    def create_collection(self, **kwargs) -> None:
        self.created.append(kwargs)

    def upsert(self, **kwargs) -> None:
        self.upserts.append(kwargs)


def test_qdrant_recreate_collection_deletes_existing_collection(monkeypatch):
    client = QdrantSearchClient()
    sdk = _FakeQdrantSdkClient()
    monkeypatch.setattr(client, "_get_client", lambda: sdk)

    client.recreate_collection(768)

    assert sdk.deleted == [client._settings.qdrant_collection]
    assert sdk.created[0]["vectors_config"].size == 768


def test_qdrant_upsert_chunks_writes_one_batch(monkeypatch):
    client = QdrantSearchClient()
    sdk = _FakeQdrantSdkClient()
    monkeypatch.setattr(client, "_get_client", lambda: sdk)

    client.upsert_chunks([
        {
            "chunk_id": "00000000-0000-0000-0000-000000000001",
            "vector": [0.1, 0.2],
            "chunk_text": "hello",
            "document_id": "doc-1",
            "source_url": "https://example.com",
            "doc_type": "faq",
            "metadata": {"page_kind": "faq"},
        }
    ])

    assert len(sdk.upserts) == 1
    point = sdk.upserts[0]["points"][0]
    assert point.payload["chunk_id"] == "00000000-0000-0000-0000-000000000001"
    assert point.payload["page_kind"] == "faq"
