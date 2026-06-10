"""Runtime LLM settings with per-model provider overrides."""

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from .config import DATA_DIR

load_dotenv()
load_dotenv(Path(__file__).with_name(".env"))

SETTINGS_PATH = Path(DATA_DIR) / "llm_settings.json"
IMPLICIT_FALLBACK_MODEL = "gpt-5-nano"
FALLBACK_MODEL_LIST_KEYS = {
    "chairman_fallback_models",
    "quick_fallback_models",
    "title_fallback_models",
    "summarization_fallback_models",
}

MODEL_ROLE_KEYS = [
    ("council", "council_models", True),
    ("chairman", "chairman_model", False),
    ("chairman_fallback", "chairman_fallback_models", True),
    ("quick", "quick_model", False),
    ("quick_fallback", "quick_fallback_models", True),
    ("title", "title_model", False),
    ("title_fallback", "title_fallback_models", True),
    ("summarization", "summarization_model", False),
    ("summarization_fallback", "summarization_fallback_models", True),
]


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return ""


DEFAULT_SETTINGS: Dict[str, Any] = {
    "default_provider": {
        "base_url": _env("OPENAI_API_BASE_URL", "OPENROUTER_API_BASE_URL"),
        "api_key": _env("OPENAI_API_KEY", "OPENROUTER_API_KEY"),
        "timeout": 180,
        "stream": True,
    },
    "council_models": [
        "anthropic/claude-sonnet-4.5",
        "gpt-5.2-chat-latest",
        "gemini-3-pro-preview",
    ],
    "chairman_model": "gemini-3-pro-preview",
    "chairman_fallback_models": [],
    "quick_model": "gemini-2.5-flash",
    "quick_fallback_models": [],
    "title_model": "gemini-2.5-flash",
    "title_fallback_models": [],
    "summarization_model": "gemini-2.5-flash",
    "summarization_fallback_models": [],
    "model_overrides": {},
}


def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_llm_settings() -> Dict[str, Any]:
    """Load settings from disk and merge with defaults."""
    if not SETTINGS_PATH.exists():
        return copy.deepcopy(DEFAULT_SETTINGS)

    with SETTINGS_PATH.open("r") as f:
        saved_settings = json.load(f)

    return _deep_merge(DEFAULT_SETTINGS, saved_settings)


def save_llm_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Persist runtime settings."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_PATH.open("w") as f:
        json.dump(settings, f, indent=2)
    return settings


def update_llm_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Merge and persist partial settings updates."""
    settings = _deep_merge(load_llm_settings(), updates)
    return save_llm_settings(settings)


def _redact_provider(provider: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(provider or {})
    api_key = redacted.pop("api_key", "")
    redacted["api_key_set"] = bool(api_key)
    return redacted


def public_llm_settings() -> Dict[str, Any]:
    """Return settings safe for API clients."""
    settings = load_llm_settings()
    public_settings = copy.deepcopy(settings)
    public_settings["default_provider"] = _redact_provider(settings.get("default_provider", {}))

    public_overrides = {}
    for model, override in settings.get("model_overrides", {}).items():
        public_overrides[model] = _redact_provider(override)
    public_settings["model_overrides"] = public_overrides
    return public_settings


def _coerce_timeout(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _configured_model_roles(settings: Dict[str, Any]) -> Dict[str, List[str]]:
    roles_by_model: Dict[str, List[str]] = {}
    for role, key, is_list in MODEL_ROLE_KEYS:
        value = settings.get(key, [] if is_list else "")
        models = value if is_list and isinstance(value, list) else [value]
        for model in models:
            clean_model = str(model or "").strip()
            if clean_model:
                roles_by_model.setdefault(clean_model, []).append(role)
    return roles_by_model


def provider_diagnostics() -> Dict[str, Any]:
    """Return read-only, secret-safe provider configuration diagnostics."""
    settings = load_llm_settings()
    default_provider = settings.get("default_provider", {}) or {}
    overrides = settings.get("model_overrides", {}) or {}
    roles_by_model = _configured_model_roles(settings)
    models = []

    for model, roles in roles_by_model.items():
        override = overrides.get(model, {}) or {}
        provider = dict(default_provider)
        provider.update({key: value for key, value in override.items() if value not in (None, "")})

        base_url = str(provider.get("base_url") or "").rstrip("/")
        timeout = _coerce_timeout(provider.get("timeout"))
        enabled = bool(provider.get("enabled", True))
        problems = []
        if not base_url:
            problems.append("missing_base_url")
        if not provider.get("api_key"):
            problems.append("missing_api_key")
        if timeout is None:
            problems.append("invalid_timeout")
        if not enabled:
            problems.append("disabled_model")

        models.append({
            "model": model,
            "roles": roles,
            "provider_source": "override" if model in overrides else "default",
            "base_url": base_url,
            "chat_url": f"{base_url}/chat/completions" if base_url else "",
            "api_key_set": bool(provider.get("api_key")),
            "timeout": timeout,
            "stream": bool(provider.get("stream", True)),
            "enabled": enabled,
            "problems": problems,
        })

    ready_models = [model for model in models if not model["problems"]]
    problem_counts: Dict[str, int] = {}
    for model in models:
        for problem in model["problems"]:
            problem_counts[problem] = problem_counts.get(problem, 0) + 1

    return {
        "schema": "llm_provider_diagnostics_v1",
        "read_only": True,
        "default_provider": _redact_provider(default_provider),
        "configured_models": sorted(roles_by_model.keys()),
        "models": models,
        "summary": {
            "configured_model_count": len(models),
            "ready_model_count": len(ready_models),
            "problem_model_count": len(models) - len(ready_models),
            "problem_counts": problem_counts,
        },
        "checks": {
            "connection": "not_run",
            "model_list": "configured_only",
            "rate_limit": "not_checked",
            "reason": "Read-only diagnostics do not call the provider or expose secrets.",
        },
    }


def resolve_model_config(model: str) -> Dict[str, Any]:
    """Resolve provider details for a model, applying per-model overrides."""
    settings = load_llm_settings()
    provider = dict(settings.get("default_provider", {}))
    override = settings.get("model_overrides", {}).get(model, {})
    provider.update({key: value for key, value in override.items() if value not in (None, "")})

    base_url = (provider.get("base_url") or "").rstrip("/")
    api_key = provider.get("api_key") or ""

    if not base_url:
        raise ValueError(f"No base_url configured for model {model}")
    if not api_key:
        raise ValueError(f"No api_key configured for model {model}")

    return {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "chat_url": f"{base_url}/chat/completions",
        "timeout": float(provider.get("timeout") or 120.0),
        "enabled": bool(provider.get("enabled", True)),
        "stream": bool(provider.get("stream", True)),
    }


def model_list(key: str) -> List[str]:
    """Read a model list from runtime settings."""
    value = load_llm_settings().get(key, [])
    configured_models = value if isinstance(value, list) else []
    if key in FALLBACK_MODEL_LIST_KEYS and not configured_models:
        return [IMPLICIT_FALLBACK_MODEL]
    return configured_models


def model_name(key: str) -> str:
    """Read a model name from runtime settings."""
    return str(load_llm_settings().get(key, "") or "")
