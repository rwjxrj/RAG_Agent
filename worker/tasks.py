"""Celery tasks for ingestion."""

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.logging import get_logger
from worker.celery_app import celery_app

logger = get_logger(__name__)


async def _ingest_one(doc: dict[str, Any]):
    """Ingest one document with async session."""
    from app.db.session import async_session_factory
    from app.services.ingestion import IngestionService

    async with async_session_factory() as session:
        svc = IngestionService()
        return await svc.ingest_document(doc, session)


@celery_app.task(bind=True, name="worker.tasks.ingest_documents")
def ingest_documents_task(self, documents: list[dict[str, Any]]):
    """Ingest multiple documents. Runs async ingestion in sync context."""
    results = []
    for i, doc in enumerate(documents):
        try:
            result = asyncio.run(_ingest_one(doc))
            results.append({"index": i, "document_id": result, "status": "ok"})
        except Exception as e:
            logger.error("ingest_document_failed", index=i, error=str(e))
            results.append({"index": i, "error": str(e), "status": "error"})

    return {"processed": len(documents), "results": results}


async def _set_vector_rebuild_status(job_id: str, **values: Any) -> None:
    from app.db.session import async_session_factory
    from app.services.vector_index_rebuild import update_rebuild_job_status

    async with async_session_factory() as session:
        await update_rebuild_job_status(session, job_id=job_id, **values)
        await session.commit()


async def _run_vector_index_rebuild(job_id: str) -> dict[str, Any]:
    from app.db.models import Chunk
    from app.db.session import async_session_factory
    from app.search.embeddings import get_embedding_provider
    from app.search.qdrant_client import QdrantSearchClient
    from app.services.embedding_config import refresh_cache as refresh_embedding_config
    from app.services.vector_index_rebuild import (
        get_current_embedding_fingerprint,
        rebuild_vector_index,
        sanitize_rebuild_error,
    )

    total = 0
    processed = 0
    try:
        await _set_vector_rebuild_status(job_id, status="running")
        async with async_session_factory() as session:
            await refresh_embedding_config(session)
            result = await session.execute(
                select(Chunk).options(joinedload(Chunk.document)).order_by(Chunk.id)
            )
            chunks = list(result.scalars().all())
        total = len(chunks)
        await _set_vector_rebuild_status(
            job_id,
            status="running",
            processed_chunks=0,
            total_chunks=total,
        )

        async def report_progress(done: int, count: int) -> None:
            nonlocal processed
            processed = done
            await _set_vector_rebuild_status(
                job_id,
                status="running",
                processed_chunks=done,
                total_chunks=count,
            )

        processed = await rebuild_vector_index(
            chunks=chunks,
            embedder=get_embedding_provider(),
            qdrant=QdrantSearchClient(),
            on_progress=report_progress,
        )
        fingerprint = get_current_embedding_fingerprint()
        await _set_vector_rebuild_status(
            job_id,
            status="ready",
            processed_chunks=processed,
            total_chunks=total,
            indexed_fingerprint=fingerprint,
        )
        return {"status": "ready", "processed_chunks": processed, "total_chunks": total}
    except Exception as exc:
        try:
            await _set_vector_rebuild_status(
                job_id,
                status="failed",
                processed_chunks=processed,
                total_chunks=total,
                error=sanitize_rebuild_error(exc),
            )
        except Exception as state_exc:
            logger.error("vector_index_rebuild_state_update_failed", job_id=job_id, error=str(state_exc))
        logger.error(
            "vector_index_rebuild_failed",
            job_id=job_id,
            error=sanitize_rebuild_error(exc),
        )
        raise


@celery_app.task(bind=True, name="worker.tasks.rebuild_vector_index")
def rebuild_vector_index_task(self):
    """Rebuild Qdrant from persisted PostgreSQL chunks using current embedding config."""
    return asyncio.run(_run_vector_index_rebuild(str(self.request.id)))
