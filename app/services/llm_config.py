"""LLM config from DB (app_config) with env fallback.

Keys: llm_model, llm_fallback_model, llm_api_key, llm_base_url,
      llm_fallback_api_key, llm_fallback_base_url.
Cache refreshed on startup and when admin updates config.
"""

import hashlib
import json
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import AppConfig

logger = get_logger(__name__)

CONFIG_KEYS = (
    "llm_model",
    "llm_fallback_model",
    "llm_api_key",
    "llm_base_url",
    "llm_fallback_api_key",
    "llm_fallback_base_url",
)
_cache: dict[str, Any] = {}
_config_version: int = 0
CACHE_TTL_SECONDS = 60


def _compute_config_hash(config_dict: dict) -> int:
    """Compute a hash of the current config values for cache isolation."""
    payload = json.dumps(config_dict, sort_keys=True)
    return int(hashlib.md5(payload.encode()).hexdigest()[:8], 16)


def get_config_version() -> int:
    """Return current config version based on content hash of cached config.

    Config changes automatically produce a new version; unchanged config
    produces the same version across process restarts.
    """
    return _config_version


async def _load_from_db(session: AsyncSession) -> dict[str, str]:
    """Load LLM config keys from app_config."""
    result: dict[str, str] = {}
    try:
        rows = await session.execute(
            select(AppConfig.key, AppConfig.value).where(AppConfig.key.in_(CONFIG_KEYS))
        )
        for key, value in rows.all():
            if value is not None and value.strip():
                result[key] = value.strip()
            elif value is not None:
                result[key] = ""  # 用户显式清空，与"未设置"区分
    except Exception as e:
        logger.warning("llm_config_load_failed", error=str(e))
    return result


async def refresh_cache(session: AsyncSession) -> None:
    """Load LLM config from DB and update in-memory cache."""
    db_values = await _load_from_db(session)
    settings = get_settings()
    _cache["llm_model"] = db_values.get("llm_model") or settings.llm_model
    _cache["llm_fallback_model"] = db_values.get("llm_fallback_model") or settings.llm_fallback_model
    _cache["llm_api_key"] = db_values.get("llm_api_key") or settings.openai_api_key
    _cache["llm_base_url"] = db_values.get("llm_base_url") or settings.openai_base_url or ""
    # fallback 字段需区分"未设置(用 env)"和"用户显式清空(存空字符串)"
    _cache["llm_fallback_api_key"] = (
        db_values["llm_fallback_api_key"]
        if "llm_fallback_api_key" in db_values
        else (settings.llm_fallback_api_key or "")
    )
    _cache["llm_fallback_base_url"] = (
        db_values["llm_fallback_base_url"]
        if "llm_fallback_base_url" in db_values
        else (settings.llm_fallback_base_url or "")
    )
    _cache["updated_at"] = time.monotonic()
    global _config_version
    hash_input = {k: v for k, v in _cache.items() if k != "updated_at"}
    _config_version = _compute_config_hash(hash_input)
    logger.info(
        "llm_config_cache_refreshed",
        llm_model=_cache["llm_model"],
        llm_fallback_model=_cache["llm_fallback_model"],
        config_version=_config_version,
    )


def get_llm_model() -> str:
    """Return primary LLM model. From DB cache or env fallback."""
    if "llm_model" in _cache:
        return _cache["llm_model"]
    return get_settings().llm_model


def get_llm_fallback_model() -> str:
    """Return fallback LLM model. From DB cache or env fallback."""
    if "llm_fallback_model" in _cache:
        return _cache["llm_fallback_model"]
    return get_settings().llm_fallback_model


def get_llm_api_key() -> str:
    """Return LLM API key (token). From DB cache or env fallback."""
    if "llm_api_key" in _cache:
        return _cache["llm_api_key"]
    return get_settings().openai_api_key


def get_llm_base_url() -> str:
    """Return LLM API base URL. From DB cache or env fallback. Empty = default OpenAI URL."""
    if "llm_base_url" in _cache:
        return _cache["llm_base_url"]
    return get_settings().openai_base_url or ""


def get_llm_fallback_api_key() -> str:
    """Return fallback LLM API key. Empty = use primary llm_api_key."""
    if "llm_fallback_api_key" in _cache:
        return _cache["llm_fallback_api_key"]
    return get_settings().llm_fallback_api_key or ""


def get_llm_fallback_base_url() -> str:
    """Return fallback LLM base URL. Empty = use primary llm_base_url."""
    if "llm_fallback_base_url" in _cache:
        return _cache["llm_fallback_base_url"]
    return get_settings().llm_fallback_base_url or ""
