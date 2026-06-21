"""Reranker config from DB (app_config) with env fallback."""

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import AppConfig

logger = get_logger(__name__)

CONFIG_KEYS = (
    "reranker_provider",
    "reranker_model",
    "reranker_url",
    "reranker_api_format",
    "reranker_base_url",
    "reranker_api_key",
)
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
        logger.warning("reranker_config_load_failed", error=str(e))
    return result


async def refresh_cache(session: AsyncSession) -> None:
    """Load reranker config from DB and update in-memory cache."""
    db_values = await _load_from_db(session)
    settings = get_settings()
    _cache["reranker_provider"] = db_values.get("reranker_provider") or settings.reranker_provider
    _cache["reranker_model"] = db_values.get("reranker_model") or settings.reranker_model
    _cache["reranker_url"] = db_values.get("reranker_url") or settings.reranker_url or ""
    _cache["reranker_api_format"] = db_values.get("reranker_api_format") or getattr(settings, "reranker_api_format", "rerank") or "rerank"
    _cache["reranker_base_url"] = db_values.get("reranker_base_url") or getattr(settings, "reranker_base_url", "") or ""
    _cache["reranker_api_key"] = db_values.get("reranker_api_key") or settings.cohere_api_key or ""
    _cache["updated_at"] = time.monotonic()
    logger.info(
        "reranker_config_cache_refreshed",
        reranker_provider=_cache["reranker_provider"],
        reranker_model=_cache["reranker_model"],
    )


def get_reranker_provider() -> str:
    if "reranker_provider" in _cache:
        return _cache["reranker_provider"]
    return get_settings().reranker_provider


def get_reranker_model() -> str:
    if "reranker_model" in _cache:
        return _cache["reranker_model"]
    return get_settings().reranker_model


def get_reranker_url() -> str:
    """For local provider: the reranker service URL."""
    if "reranker_url" in _cache:
        return _cache["reranker_url"]
    return get_settings().reranker_url or ""


def get_reranker_api_format() -> str:
    """For cloud provider: 'rerank' or 'openai'."""
    if "reranker_api_format" in _cache:
        return _cache["reranker_api_format"]
    return getattr(get_settings(), "reranker_api_format", "rerank") or "rerank"


def get_reranker_base_url() -> str:
    """For cloud provider: the API base URL."""
    if "reranker_base_url" in _cache:
        return _cache["reranker_base_url"]
    return getattr(get_settings(), "reranker_base_url", "") or ""


def get_reranker_api_key() -> str:
    """API key for cloud reranker (unified field, replaces cohere_api_key)."""
    if "reranker_api_key" in _cache:
        return _cache["reranker_api_key"]
    return get_settings().cohere_api_key or ""


# Backward compat alias
def get_cohere_api_key() -> str:
    return get_reranker_api_key()
