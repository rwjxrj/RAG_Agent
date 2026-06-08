"""Tests for environment-backed application settings."""

from app.core.config import get_settings


def test_generate_reasoning_settings_are_env_backed(monkeypatch):
    monkeypatch.setenv("GENERATE_REASONING_ENABLED", "false")
    monkeypatch.setenv("GENERATE_REASONING_MAX_CHUNKS", "4")
    monkeypatch.setenv("GENERATE_REASONING_MAX_OPTIONS", "2")
    monkeypatch.setenv("GENERATE_REASONING_MAX_TOKENS", "128")
    get_settings.cache_clear()
    try:
        settings = get_settings()

        assert settings.generate_reasoning_enabled is False
        assert settings.generate_reasoning_max_chunks == 4
        assert settings.generate_reasoning_max_options == 2
        assert settings.generate_reasoning_max_tokens == 128
    finally:
        get_settings.cache_clear()
