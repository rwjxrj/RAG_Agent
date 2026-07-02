"""Vector-index rebuild state and orchestration helpers."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any, Awaitable, Callable, Iterable

from sqlalchemy import select, text

from app.db.models import AppConfig, generate_uuid


VECTOR_INDEX_STATE_KEY = "vector_index_rebuild_state"
VECTOR_INDEX_PROBE_TEXT = "vector index readiness probe"
VECTOR_INDEX_BATCH_SIZE = 32
TERMINAL_STATUSES = {"ready", "required", "failed"}
ACTIVE_STATUSES = {"queued", "running"}
VECTOR_INDEX_LOCK_ID = 824_721_903


class VectorIndexMaintenanceError(RuntimeError):
    """Raised when vector-backed work is disabled during index maintenance."""


class VectorIndexConflictError(RuntimeError):
    """Raised when an index operation conflicts with an active rebuild."""


@dataclass(slots=True)
class VectorIndexStatus:
    status: str = "ready"
    job_id: str | None = None
    processed_chunks: int = 0
    total_chunks: int = 0
    error: str | None = None
    updated_at: datetime | None = None
    indexed_fingerprint: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "job_id": self.job_id,
                "processed_chunks": self.processed_chunks,
                "total_chunks": self.total_chunks,
                "error": self.error,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                "indexed_fingerprint": self.indexed_fingerprint,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, value: str | None) -> "VectorIndexStatus":
        if not value:
            return cls()
        try:
            data = json.loads(value)
            updated_at = data.get("updated_at")
            return cls(
                status=str(data.get("status") or "ready"),
                job_id=data.get("job_id"),
                processed_chunks=max(0, int(data.get("processed_chunks") or 0)),
                total_chunks=max(0, int(data.get("total_chunks") or 0)),
                error=data.get("error"),
                updated_at=datetime.fromisoformat(updated_at) if updated_at else None,
                indexed_fingerprint=data.get("indexed_fingerprint"),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return cls(status="failed", error="Invalid vector index state")


def build_embedding_fingerprint(
    provider: str,
    model: str,
    dimensions: int,
    base_url: str,
    api_key: str = "",
) -> str:
    """Build a stable vector-space identity. Credentials are intentionally excluded."""
    del api_key
    payload = {
        "provider": provider.strip().lower(),
        "model": model.strip(),
        "dimensions": int(dimensions),
        "base_url": base_url.strip().rstrip("/").lower(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint_from_mapping(config: dict[str, Any]) -> str:
    return build_embedding_fingerprint(
        provider=str(config.get("embedding_provider") or ""),
        model=str(config.get("embedding_model") or ""),
        dimensions=int(config.get("embedding_dimensions") or 0),
        base_url=str(config.get("embedding_base_url") or ""),
        api_key=str(config.get("embedding_api_key") or ""),
    )


def vector_space_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return _fingerprint_from_mapping(before) != _fingerprint_from_mapping(after)


async def _lock_vector_index_state(session: Any) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": VECTOR_INDEX_LOCK_ID},
    )


async def _get_state_row(session: Any) -> AppConfig | None:
    result = await session.execute(
        select(AppConfig).where(AppConfig.key == VECTOR_INDEX_STATE_KEY).limit(1)
    )
    return result.scalar_one_or_none()


async def get_vector_index_status(session: Any) -> VectorIndexStatus:
    row = await _get_state_row(session)
    return VectorIndexStatus.from_json(row.value if row else None)


async def save_vector_index_status(
    session: Any,
    status: VectorIndexStatus,
    *,
    lock: bool = True,
) -> VectorIndexStatus:
    if lock:
        await _lock_vector_index_state(session)
    row = await _get_state_row(session)
    status.updated_at = datetime.now(timezone.utc)
    value = status.to_json()
    if row is None:
        row = AppConfig(id=generate_uuid(), key=VECTOR_INDEX_STATE_KEY, value=value)
        session.add(row)
    else:
        row.value = value
    await session.flush()
    return status


async def ensure_vector_index_ready(session: Any) -> VectorIndexStatus:
    status = await get_vector_index_status(session)
    if not status.is_ready:
        raise VectorIndexMaintenanceError("向量索引维护中，知识库问答暂不可用。")
    return status


async def lock_embedding_config_for_update(session: Any) -> VectorIndexStatus:
    await _lock_vector_index_state(session)
    status = await get_vector_index_status(session)
    if status.status in ACTIVE_STATUSES:
        raise VectorIndexConflictError("重建期间不能修改向量化配置。")
    return status


async def refresh_embedding_runtime_if_ready() -> None:
    """Synchronize process-local embedding config after confirming index readiness."""
    from app.db.session import async_session_factory
    from app.services.embedding_config import refresh_cache as refresh_embedding_config

    async with async_session_factory() as session:
        await ensure_vector_index_ready(session)
        await refresh_embedding_config(session)


async def queue_vector_index_rebuild(
    session: Any,
    job_id: str,
    *,
    lock: bool = True,
) -> VectorIndexStatus:
    if lock:
        await _lock_vector_index_state(session)
    current = await get_vector_index_status(session)
    if current.status in ACTIVE_STATUSES:
        raise VectorIndexConflictError("已有向量索引重建任务正在执行。")
    queued = VectorIndexStatus(
        status="queued",
        job_id=job_id,
        processed_chunks=0,
        total_chunks=0,
        indexed_fingerprint=current.indexed_fingerprint,
    )
    return await save_vector_index_status(session, queued, lock=False)


async def mark_vector_index_rebuild_required(
    session: Any,
    *,
    indexed_fingerprint: str | None,
    lock: bool = True,
) -> VectorIndexStatus:
    if lock:
        await _lock_vector_index_state(session)
    current = await get_vector_index_status(session)
    if current.status in ACTIVE_STATUSES:
        raise VectorIndexConflictError("重建期间不能修改向量化配置。")
    required = VectorIndexStatus(
        status="required",
        indexed_fingerprint=indexed_fingerprint or current.indexed_fingerprint,
    )
    return await save_vector_index_status(session, required, lock=False)


async def update_rebuild_job_status(
    session: Any,
    *,
    job_id: str,
    status: str,
    processed_chunks: int = 0,
    total_chunks: int = 0,
    error: str | None = None,
    indexed_fingerprint: str | None = None,
) -> VectorIndexStatus:
    await _lock_vector_index_state(session)
    current = await get_vector_index_status(session)
    if current.job_id != job_id:
        raise VectorIndexConflictError("向量索引任务状态已变化。")
    updated = VectorIndexStatus(
        status=status,
        job_id=job_id,
        processed_chunks=processed_chunks,
        total_chunks=total_chunks,
        error=error,
        indexed_fingerprint=indexed_fingerprint or current.indexed_fingerprint,
    )
    return await save_vector_index_status(session, updated, lock=False)


def get_current_embedding_fingerprint() -> str:
    from app.services.embedding_config import (
        get_embedding_api_key,
        get_embedding_base_url,
        get_embedding_dimensions,
        get_embedding_model,
        get_embedding_provider_name,
    )

    return build_embedding_fingerprint(
        get_embedding_provider_name(),
        get_embedding_model(),
        get_embedding_dimensions(),
        get_embedding_base_url(),
        get_embedding_api_key(),
    )


def sanitize_rebuild_error(
    error: Exception,
    *,
    secrets: Iterable[str] | None = None,
) -> str:
    message = str(error).strip() or error.__class__.__name__
    if secrets is None:
        try:
            from app.services.embedding_config import get_embedding_api_key
            from app.services.llm_config import get_llm_api_key

            secrets = [get_embedding_api_key(), get_llm_api_key()]
        except Exception:
            secrets = []
    for secret in secrets:
        if secret and len(secret) >= 4:
            message = message.replace(secret, "[REDACTED]")
    return message[:500]


async def _notify_progress(
    callback: Callable[[int, int], Any] | None,
    processed: int,
    total: int,
) -> None:
    if callback is None:
        return
    result = callback(processed, total)
    if inspect.isawaitable(result):
        await result


def _chunk_payload(chunk: Any, vector: list[float]) -> dict[str, Any]:
    document = chunk.document
    return {
        "chunk_id": str(chunk.id),
        "vector": vector,
        "chunk_text": chunk.chunk_text,
        "document_id": str(chunk.document_id),
        "source_url": document.source_url,
        "doc_type": document.doc_type,
        "metadata": dict(chunk.chunk_metadata or {}),
    }


async def rebuild_vector_index(
    *,
    chunks: Iterable[Any],
    embedder: Any,
    qdrant: Any,
    batch_size: int = VECTOR_INDEX_BATCH_SIZE,
    on_progress: Callable[[int, int], Awaitable[None] | None] | None = None,
) -> int:
    """Probe the embedding model, recreate Qdrant, and repopulate it from DB chunks."""
    dimensions = int(embedder.dimensions())
    probe_vectors = await embedder.embed([VECTOR_INDEX_PROBE_TEXT])
    if len(probe_vectors) != 1 or len(probe_vectors[0]) != dimensions:
        actual = len(probe_vectors[0]) if probe_vectors else 0
        raise ValueError(
            f"Embedding probe returned dimension {actual}; configured dimensions {dimensions}"
        )

    all_chunks = list(chunks)
    qdrant.recreate_collection(dimensions)
    total = len(all_chunks)
    processed = 0
    for offset in range(0, total, max(1, batch_size)):
        batch = all_chunks[offset : offset + max(1, batch_size)]
        vectors = await embedder.embed([chunk.chunk_text for chunk in batch])
        if len(vectors) != len(batch):
            raise ValueError(
                f"Embedding provider returned {len(vectors)} vectors for {len(batch)} chunks"
            )
        for vector in vectors:
            if len(vector) != dimensions:
                raise ValueError(
                    f"Embedding returned dimension {len(vector)}; configured dimensions {dimensions}"
                )
        qdrant.upsert_chunks([
            _chunk_payload(chunk, vector)
            for chunk, vector in zip(batch, vectors, strict=True)
        ])
        processed += len(batch)
        await _notify_progress(on_progress, processed, total)
    return processed
