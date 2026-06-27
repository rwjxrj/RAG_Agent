"""Tests for the source ingestion CLI helpers."""

import importlib.util
from pathlib import Path


def _load_ingest_script():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ingest_from_source.py"
    spec = importlib.util.spec_from_file_location("ingest_from_source_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_run_ingest_refreshes_embedding_config_before_service_init(monkeypatch):
    module = _load_ingest_script()
    calls = []

    async def fake_ensure_migrations():
        calls.append("migrations")

    def fake_session_factory():
        calls.append("session")
        return _FakeSession()

    async def fake_refresh_cache(session):
        assert isinstance(session, _FakeSession)
        calls.append("refresh_embedding")

    class FakeIngestionService:
        def __init__(self):
            calls.append("service_init")

    monkeypatch.setattr(module, "ensure_migrations", fake_ensure_migrations)

    import app.db.session as db_session
    import app.services.embedding_config as embedding_config
    import app.services.ingestion as ingestion

    monkeypatch.setattr(db_session, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(embedding_config, "refresh_cache", fake_refresh_cache)
    monkeypatch.setattr(ingestion, "IngestionService", FakeIngestionService)

    import asyncio

    results = asyncio.run(module.run_ingest([]))

    assert results == {"ok": 0, "skipped": 0, "error": 0}
    assert calls == ["migrations", "session", "refresh_embedding", "service_init"]


def test_run_ingest_passes_force_reindex_when_skip_existing_is_false(monkeypatch):
    module = _load_ingest_script()
    force_values = []

    async def fake_ensure_migrations():
        return None

    def fake_session_factory():
        return _FakeSession()

    async def fake_refresh_cache(_session):
        return None

    class FakeIngestionService:
        async def ingest_document(self, _doc, _session, *, force_reindex=False):
            force_values.append(force_reindex)
            return "doc-id"

    monkeypatch.setattr(module, "ensure_migrations", fake_ensure_migrations)

    import app.db.session as db_session
    import app.services.embedding_config as embedding_config
    import app.services.ingestion as ingestion

    monkeypatch.setattr(db_session, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(embedding_config, "refresh_cache", fake_refresh_cache)
    monkeypatch.setattr(ingestion, "IngestionService", FakeIngestionService)

    import asyncio

    results = asyncio.run(module.run_ingest([{"url": "eval://retrieval/doc-001"}], skip_existing=False))

    assert results == {"ok": 1, "skipped": 0, "error": 0}
    assert force_values == [True]
