"""Embedding config from DB (app_config) with env fallback."""

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import AppConfig
from app.services.llm_config import get_llm_api_key, get_llm_base_url

logger = get_logger(__name__)

CONFIG_KEYS = (
    "embedding_provider",
    "embedding_model",
    "embedding_dimensions",
    "embedding_api_key",
    "embedding_base_url",
)
OLLAMA_DEFAULT_BASE_URL = "http://host.docker.internal:11434"
_cache: dict[str, Any] = {}


async def _load_from_db(session: AsyncSession) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        rows = await session.execute(
            select(AppConfig.key, AppConfig.value).where(AppConfig.key.in_(CONFIG_KEYS))
        )
        for key, value in rows.all():
            if value and value.strip():
                result[key] = value.strip()
    except Exception as e:
        logger.warning("embedding_config_load_failed", error=str(e))
    return result


def _parse_dimensions(value: str | int | None, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


async def refresh_cache(session: AsyncSession) -> None:
    """Load embedding config from DB and update in-memory cache."""
    db_values = await _load_from_db(session)
    settings = get_settings()
    _cache["embedding_provider"] = db_values.get("embedding_provider") or settings.embedding_provider
    _cache["embedding_model"] = db_values.get("embedding_model") or settings.embedding_model
    _cache["embedding_dimensions"] = _parse_dimensions(
        db_values.get("embedding_dimensions"),
        settings.embedding_dimensions,
    )
    _cache["embedding_api_key"] = db_values.get("embedding_api_key") or settings.embedding_api_key or ""
    _cache["embedding_base_url"] = db_values.get("embedding_base_url") or settings.embedding_base_url or ""
    _cache["updated_at"] = time.monotonic()
    logger.info(
        "embedding_config_cache_refreshed",
        embedding_provider=_cache["embedding_provider"],
        embedding_model=_cache["embedding_model"],
        embedding_dimensions=_cache["embedding_dimensions"],
    )


def get_embedding_provider_name() -> str:
    if "embedding_provider" in _cache:
        return _cache["embedding_provider"]
    return get_settings().embedding_provider


def get_embedding_model() -> str:
    if "embedding_model" in _cache:
        return _cache["embedding_model"]
    return get_settings().embedding_model


def get_embedding_dimensions() -> int:
    if "embedding_dimensions" in _cache:
        return int(_cache["embedding_dimensions"])
    return get_settings().embedding_dimensions


def get_embedding_api_key() -> str:
    provider = get_embedding_provider_name()
    if "embedding_api_key" in _cache and _cache["embedding_api_key"]:
        return _cache["embedding_api_key"]
    api_key = get_settings().embedding_api_key or ""
    if api_key or provider == "ollama":
        return api_key
    return get_llm_api_key()


def get_embedding_base_url() -> str:
    provider = get_embedding_provider_name()
    base_url = _cache.get("embedding_base_url") if "embedding_base_url" in _cache else get_settings().embedding_base_url
    base_url = (base_url or "").strip()
    if base_url:
        return base_url
    if provider == "ollama":
        return OLLAMA_DEFAULT_BASE_URL
    return get_llm_base_url()
