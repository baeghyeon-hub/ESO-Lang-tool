"""
번역 설정 관리 — API 키, 모델, 배치 파라미터.

프로젝트 디렉토리의 settings.json에 저장.
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ---------------------------------------------------------------------------
# 프로바이더별 모델 목록 (하드코딩)
# ---------------------------------------------------------------------------

PROVIDER_MODELS: dict[str, list[str]] = {
    "gemini": ["gemini-3-flash-preview", "gemini-2.5-flash"],
    "claude": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "gpt": ["gpt-4o", "gpt-4o-mini"],
}

PROVIDER_LABELS: dict[str, str] = {
    "gemini": "Google Gemini",
    "claude": "Anthropic Claude",
    "gpt": "OpenAI GPT",
}

DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini-3-flash-preview",
    "claude": "claude-sonnet-4-6",
    "gpt": "gpt-4o",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    api_key: str = ""
    model: str = ""


@dataclass
class TranslationSettings:
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    active_provider: str = "gemini"
    batch_size: int = 20
    max_retries: int = 2
    glossary_injection: bool = True
    auto_apply_duplicates: bool = True

    def __post_init__(self):
        # 누락된 프로바이더 기본값 채우기
        for name in PROVIDER_MODELS:
            if name not in self.providers:
                self.providers[name] = ProviderConfig(
                    model=DEFAULT_MODELS.get(name, ""),
                )

    @property
    def active_api_key(self) -> str:
        cfg = self.providers.get(self.active_provider)
        return cfg.api_key if cfg else ""

    @property
    def active_model(self) -> str:
        cfg = self.providers.get(self.active_provider)
        return cfg.model if cfg else ""


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

_SETTINGS_FILENAME = "settings.json"


class ConfigManager:
    """프로젝트 디렉토리 기반 설정 관리."""

    def __init__(self, config_dir: Path | None = None):
        self._dir = config_dir or Path.cwd()
        self._path = self._dir / _SETTINGS_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> TranslationSettings:
        """설정 파일 로드. 없으면 기본값 반환."""
        if not self._path.exists():
            return TranslationSettings()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return self._from_dict(raw)
        except (json.JSONDecodeError, KeyError, TypeError):
            return TranslationSettings()

    def save(self, settings: TranslationSettings) -> None:
        """설정을 JSON으로 저장."""
        self._dir.mkdir(parents=True, exist_ok=True)
        data = self._to_dict(settings)
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # 직렬화
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(settings: TranslationSettings) -> dict:
        providers = {}
        for name, cfg in settings.providers.items():
            providers[name] = asdict(cfg)
        return {
            "providers": providers,
            "active_provider": settings.active_provider,
            "batch_size": settings.batch_size,
            "max_retries": settings.max_retries,
            "glossary_injection": settings.glossary_injection,
            "auto_apply_duplicates": settings.auto_apply_duplicates,
        }

    @staticmethod
    def _from_dict(raw: dict) -> TranslationSettings:
        providers = {}
        for name, cfg_dict in raw.get("providers", {}).items():
            providers[name] = ProviderConfig(
                api_key=cfg_dict.get("api_key", ""),
                model=cfg_dict.get("model", DEFAULT_MODELS.get(name, "")),
            )
        return TranslationSettings(
            providers=providers,
            active_provider=raw.get("active_provider", "gemini"),
            batch_size=raw.get("batch_size", 20),
            max_retries=raw.get("max_retries", 2),
            glossary_injection=raw.get("glossary_injection", True),
            auto_apply_duplicates=raw.get("auto_apply_duplicates", True),
        )
