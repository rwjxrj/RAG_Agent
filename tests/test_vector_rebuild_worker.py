from types import SimpleNamespace

import pytest

from app.services import embedding_config, vector_index_rebuild
from app.search import embeddings
from worker import tasks


class _FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, _statement):
        return _FakeResult()


@pytest.mark.asyncio
async def test_vector_rebuild_worker_marks_failed_without_retrying_task(monkeypatch):
    status_updates: list[dict] = []

    async def record_status(job_id: str, **values):
        status_updates.append({"job_id": job_id, **values})

    async def fail_rebuild(**_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(tasks, "_set_vector_rebuild_status", record_status)
    monkeypatch.setattr("app.db.session.async_session_factory", _FakeSession)
    monkeypatch.setattr(embedding_config, "refresh_cache", lambda _session: _async_none())
    monkeypatch.setattr(embeddings, "get_embedding_provider", lambda: SimpleNamespace())
    monkeypatch.setattr(vector_index_rebuild, "rebuild_vector_index", fail_rebuild)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await tasks._run_vector_index_rebuild("job-1")

    assert [update["status"] for update in status_updates] == ["running", "running", "failed"]
    assert status_updates[-1]["error"] == "provider unavailable"


async def _async_none():
    return None
