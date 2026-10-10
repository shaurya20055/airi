"""Tests for app.core.config.settings."""
from __future__ import annotations

import os
import pytest
from app.core.config.settings import Settings, get_settings, AIProviderType


def test_default_values():
    """Settings should have sensible defaults."""
    s = Settings()
    assert s.ai_provider == AIProviderType.LOCAL
    assert s.log_level == "INFO"
    assert s.avatar_enabled is True
    assert s.stt_provider == "faster-whisper"
    assert s.tts_provider == "kokoro"


def test_openai_key_empty_by_default():
    s = Settings()
    assert s.openai_api_key == ""


def test_permission_default():
    s = Settings()
    assert s.permission_default.value == "confirm"


def test_get_settings_returns_same_instance():
    """get_settings() is a singleton."""
    # Reset global
    import app.core.config.settings as mod
    mod._settings_instance = None
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
    mod._settings_instance = None  # cleanup


def test_openai_fallback_to_local(monkeypatch):
    """If OpenAI provider chosen but no key, fall back to local."""
    import app.core.config.settings as mod
    mod._settings_instance = None
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    s = get_settings()
    assert s.ai_provider == AIProviderType.LOCAL
    mod._settings_instance = None


def test_inference_device_settings():
    """Verify inference devices default to stable config: GPU for local AI, CPU int8 for STT, CPU for TTS."""
    s = Settings()
    assert s.local_ai_device == "gpu"
    assert s.stt_device == "cpu"
    assert s.stt_compute_type == "int8"
    assert s.tts_device == "cpu"
    assert s.save_diagnostic_audio is False
    assert s.diagnostic_audio_dir == "data/diagnostics/audio"

