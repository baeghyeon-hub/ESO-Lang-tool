"""core/config.py 테스트."""

import json
from pathlib import Path

from core.config import ConfigManager, TranslationSettings, ProviderConfig


def test_config_defaults():
    """기본값으로 생성된 설정."""
    settings = TranslationSettings()
    assert settings.active_provider == "gemini"
    assert settings.batch_size == 20
    assert "gemini" in settings.providers
    assert "claude" in settings.providers
    assert "gpt" in settings.providers
    assert settings.providers["gemini"].model == "gemini-3-flash-preview"


def test_config_save_load_roundtrip(tmp_path):
    """저장/로드 라운드트립."""
    mgr = ConfigManager(config_dir=tmp_path)

    settings = TranslationSettings()
    settings.providers["gemini"].api_key = "test-key-123"
    settings.batch_size = 30
    settings.active_provider = "gemini"

    mgr.save(settings)
    assert (tmp_path / "settings.json").exists()

    loaded = mgr.load()
    assert loaded.providers["gemini"].api_key == "test-key-123"
    assert loaded.batch_size == 30
    assert loaded.active_provider == "gemini"


def test_config_missing_file_creates_defaults(tmp_path):
    """설정 파일이 없으면 기본값 반환."""
    mgr = ConfigManager(config_dir=tmp_path)
    settings = mgr.load()
    assert settings.active_provider == "gemini"
    assert settings.providers["gemini"].api_key == ""


def test_config_corrupt_file(tmp_path):
    """손상된 JSON은 기본값 반환."""
    (tmp_path / "settings.json").write_text("not json", encoding="utf-8")
    mgr = ConfigManager(config_dir=tmp_path)
    settings = mgr.load()
    assert settings.active_provider == "gemini"


def test_config_api_key_persistence(tmp_path):
    """API 키가 저장/로드 시 유지."""
    mgr = ConfigManager(config_dir=tmp_path)

    settings = TranslationSettings()
    settings.providers["gemini"].api_key = "AIza_secret"
    settings.providers["claude"].api_key = "sk-ant-secret"
    mgr.save(settings)

    loaded = mgr.load()
    assert loaded.providers["gemini"].api_key == "AIza_secret"
    assert loaded.providers["claude"].api_key == "sk-ant-secret"


def test_config_active_properties():
    """active_api_key / active_model 프로퍼티."""
    settings = TranslationSettings()
    settings.providers["gemini"].api_key = "key123"
    settings.providers["gemini"].model = "gemini-3-flash-preview"
    settings.active_provider = "gemini"

    assert settings.active_api_key == "key123"
    assert settings.active_model == "gemini-3-flash-preview"
