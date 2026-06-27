"""Tests for ingestion idempotent update behavior."""

import asyncio
from types import SimpleNamespace

from app.services.ingestion import IngestionService, _checksum, prepare_document


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _FakeExecuteResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return _FakeScalarResult(self._value)


class _FakeSession:
    def __init__(self, existing):
        self._existing = existing
        self.flush_count = 0
        self.commit_count = 0

    async def execute(self, _statement):
        return _FakeExecuteResult(self._existing)

    async def flush(self):
        self.flush_count += 1

    async def commit(self):
        self.commit_count += 1


def test_unchanged_document_metadata_update_is_committed():
    doc = {
        "url": "eval://retrieval/doc-001",
        "title": "新标题",
        "doc_type": "faq",
        "raw_text": "棉岚服饰线上客服采用分段值班。工作日在线接待为9:00至22:30，周六、周日为10:00至22:00。机器人可全天提供订单流程、退换货入口和常见政策说明。",
        "metadata": {"source": "synthetic_retrieval_benchmark_v1"},
        "source_file": "retrieval_benchmark_v1.json",
    }
    cleaned, _raw, _chunks = prepare_document(doc)
    existing = SimpleNamespace(
        id="doc-id",
        checksum=_checksum(cleaned),
        title="旧标题",
        doc_type="retrieval_benchmark_v1",
        effective_date=None,
        doc_metadata={},
        source_file="old.json",
        updated_at=None,
    )
    session = _FakeSession(existing)
    service = IngestionService(opensearch=object(), qdrant=object(), embedder=object())

    result = asyncio.run(service.ingest_document(doc, session))

    assert result == "doc-id"
    assert existing.title == "新标题"
    assert existing.doc_type == "faq"
    assert existing.source_file == "retrieval_benchmark_v1.json"
    assert session.flush_count == 1
    assert session.commit_count == 1
