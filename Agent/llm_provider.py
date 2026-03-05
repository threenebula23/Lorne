"""
LLM Provider for TCA — manages model profiles, config persistence, and OpenRouter API.
Includes provider capability detection to avoid incompatible API parameters.
"""
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_openai import ChatOpenAI

ProfileName = str

_CONFIG_PATH = Path.home() / ".tca_config.json"

# ─── Provider capabilities ──────────────────────────────────────────
# Maps provider prefix → supported features.
# parallel_tool_calls: safe to pass parallel_tool_calls=False to bind_tools
#   (OpenAI natively supports it; others may reject the extra key via OpenRouter)
_PROVIDER_CAPS: Dict[str, Dict[str, bool]] = {
    "openai/":      {"parallel_tool_calls": True,  "native_tools": True},
    "anthropic/":   {"parallel_tool_calls": False, "native_tools": True},
    "meta-llama/":  {"parallel_tool_calls": False, "native_tools": True},
    "deepseek/":    {"parallel_tool_calls": False, "native_tools": True},
    "google/":      {"parallel_tool_calls": False, "native_tools": True},
    "qwen/":        {"parallel_tool_calls": False, "native_tools": True},
    "mistralai/":   {"parallel_tool_calls": False, "native_tools": True},
}


def get_model_capabilities(model_id: str) -> Dict[str, bool]:
    """Return capability flags for a given model based on its provider prefix."""
    for prefix, caps in _PROVIDER_CAPS.items():
        if (model_id or "").startswith(prefix):
            return dict(caps)
    return {"parallel_tool_calls": False, "native_tools": True}


def supports_parallel_tool_calls_param(model_id: str) -> bool:
    """Check if the model's provider supports the parallel_tool_calls binding parameter."""
    return get_model_capabilities(model_id).get("parallel_tool_calls", False)


def is_reasoning_model(model_id: str) -> bool:
    """Check if the model is a reasoning/thinking model that emits <think> blocks."""
    _id = (model_id or "").lower()
    return any(tag in _id for tag in ("deepseek-r1", "qwq", "/o1", "/o3", "/o4"))


# ─── Popular OpenRouter models (curated, updated Feb 2026) ───────
AVAILABLE_MODELS: List[Dict[str, Any]] = [
    # --- free ---
    {"id": "meta-llama/llama-4-scout:free",             "name": "Llama 4 Scout",         "ctx": 512_000,    "tier": "free"},
    {"id": "meta-llama/llama-4-maverick:free",          "name": "Llama 4 Maverick",      "ctx": 256_000,    "tier": "free"},
    {"id": "meta-llama/llama-3.3-70b-instruct",        "name": "Llama 3.3 70B",         "ctx": 131_072,    "tier": "free"},
    {"id": "deepseek/deepseek-r1:free",                 "name": "DeepSeek R1 (free)",    "ctx": 164_000,    "tier": "free"},
    {"id": "qwen/qwen-2.5-coder-32b-instruct",         "name": "Qwen 2.5 Coder 32B",   "ctx": 32_768,     "tier": "free"},
    {"id": "google/gemma-3-27b-it:free",                "name": "Gemma 3 27B",           "ctx": 131_072,    "tier": "free"},
    # --- cheap ---
    {"id": "deepseek/deepseek-chat",                    "name": "DeepSeek V3",           "ctx": 164_000,    "tier": "cheap"},
    {"id": "deepseek/deepseek-r1",                      "name": "DeepSeek R1",           "ctx": 164_000,    "tier": "cheap"},
    {"id": "deepseek/deepseek-r1-0528",                 "name": "DeepSeek R1 0528",      "ctx": 164_000,    "tier": "cheap"},
    {"id": "qwen/qwq-32b",                              "name": "QwQ 32B",               "ctx": 131_072,    "tier": "cheap"},
    {"id": "google/gemini-2.5-flash-preview",           "name": "Gemini 2.5 Flash",      "ctx": 1_048_576,  "tier": "cheap"},
    {"id": "openai/gpt-4.1-mini",                       "name": "GPT-4.1 Mini",          "ctx": 1_047_576,  "tier": "cheap"},
    {"id": "openai/gpt-4.1-nano",                       "name": "GPT-4.1 Nano",          "ctx": 1_047_576,  "tier": "cheap"},
    {"id": "openai/o4-mini",                             "name": "O4 Mini",               "ctx": 200_000,    "tier": "cheap"},
    {"id": "anthropic/claude-3.5-haiku",                "name": "Claude 3.5 Haiku",      "ctx": 200_000,    "tier": "cheap"},
    # --- paid ---
    {"id": "openai/gpt-4.1",                            "name": "GPT-4.1",               "ctx": 1_047_576,  "tier": "paid"},
    {"id": "openai/o3",                                  "name": "O3",                    "ctx": 200_000,    "tier": "paid"},
    {"id": "google/gemini-2.5-pro-preview",             "name": "Gemini 2.5 Pro",        "ctx": 1_048_576,  "tier": "paid"},
    {"id": "anthropic/claude-sonnet-4",                 "name": "Claude Sonnet 4",       "ctx": 200_000,    "tier": "paid"},
    {"id": "anthropic/claude-sonnet-4.5",               "name": "Claude Sonnet 4.5",     "ctx": 200_000,    "tier": "paid"},
    {"id": "anthropic/claude-opus-4",                   "name": "Claude Opus 4",         "ctx": 200_000,    "tier": "paid"},
    {"id": "anthropic/claude-opus-4.5",                 "name": "Claude Opus 4.5",       "ctx": 200_000,    "tier": "paid"},
    {"id": "mistralai/mistral-large",                   "name": "Mistral Large",         "ctx": 131_072,    "tier": "paid"},
]


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default or ""
    return value


# ─── Config persistence ────────────────────────────────────────────

def load_config() -> Dict[str, Any]:
    try:
        if _CONFIG_PATH.exists():
            return json.loads(_CONFIG_PATH.read_text("utf-8"))
    except Exception:
        pass
    return {}


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        existing = load_config()
        existing.update(cfg)
        _CONFIG_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False), "utf-8")
    except Exception:
        pass


def get_saved_model() -> Optional[str]:
    return load_config().get("model")


def save_model_choice(model_id: str) -> None:
    save_config({"model": model_id})


# ─── Profiles ──────────────────────────────────────────────────────

def _resolve_default_model() -> str:
    """Priority: env var > saved config > hardcoded default."""
    env_model = _env("TCA_MODEL")
    if env_model:
        return env_model
    saved = get_saved_model()
    if saved:
        return saved
    return "meta-llama/llama-3.1-8b-instruct"


def _build_profiles() -> Dict[ProfileName, Dict[str, object]]:
    base_model = _resolve_default_model()
    return {
        "fast": {
            "model": _env("TCA_MODEL_FAST", base_model),
            "temperature": float(_env("TCA_TEMP_FAST", "0.1")),
            "max_tokens": int(_env("TCA_MAX_TOKENS_FAST", _env("TCA_MAX_TOKENS", "4096"))),
        },
        "balanced": {
            "model": _env("TCA_MODEL_BALANCED", base_model),
            "temperature": float(_env("TCA_TEMP_BALANCED", "0.2")),
            "max_tokens": int(_env("TCA_MAX_TOKENS_BALANCED", _env("TCA_MAX_TOKENS", "8192"))),
        },
        "quality": {
            "model": _env("TCA_MODEL_QUALITY", base_model),
            "temperature": float(_env("TCA_TEMP_QUALITY", "0.1")),
            "max_tokens": int(_env("TCA_MAX_TOKENS_QUALITY", _env("TCA_MAX_TOKENS", "16384"))),
        },
    }


_PROFILES: Dict[ProfileName, Dict[str, object]] = _build_profiles()


def reload_profiles() -> None:
    """Rebuild profiles after model change."""
    global _PROFILES
    _PROFILES = _build_profiles()


def get_available_profiles() -> Dict[ProfileName, Dict[str, object]]:
    return dict(_PROFILES)


def normalize_profile(name: str | None) -> ProfileName:
    if not name:
        env_profile = _env("TCA_PROFILE", "balanced").lower()
        name = env_profile or "balanced"
    name = name.lower().strip()
    if name in _PROFILES:
        return name
    aliases = {
        "f": "fast", "fast-profile": "fast",
        "q": "quality", "quality-profile": "quality", "hi": "quality", "high": "quality",
        "b": "balanced", "balanced-profile": "balanced", "mid": "balanced", "medium": "balanced",
    }
    return aliases.get(name, "balanced")


def get_llm(profile: str | None = None) -> Tuple[ChatOpenAI, ProfileName, str]:
    profile_name = normalize_profile(profile)
    cfg = _PROFILES[profile_name]
    model_name = str(cfg["model"])
    temperature = float(cfg["temperature"])
    max_tokens = int(cfg.get("max_tokens", 16384))

    base_url = _env("TCA_BASE_URL", "https://openrouter.ai/api/v1")
    api_key = _env("OPENROUTER_API_KEY", "")

    llm = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        request_timeout=120,
        max_retries=3,
    )
    return llm, profile_name, model_name


def set_model(model_id: str) -> str:
    """Set model, persist, and rebuild profiles. Returns the model_id."""
    save_model_choice(model_id)
    reload_profiles()
    return model_id


# ─── OpenRouter API ────────────────────────────────────────────────

def fetch_openrouter_credits() -> Optional[Dict[str, Any]]:
    """Fetch account credits/usage from OpenRouter API.
    Returns dict with 'usage', 'limit', 'is_free_tier', 'rate_limit' or None on error.
    """
    api_key = _env("OPENROUTER_API_KEY", "")
    if not api_key:
        return None

    url = "https://openrouter.ai/api/v1/auth/key"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", data)
    except Exception:
        return None


def format_credits_info(data: Dict[str, Any]) -> str:
    """Format credits data into a readable string."""
    usage = data.get("usage", 0)
    limit = data.get("limit")
    is_free = data.get("is_free_tier", True)

    usage_daily = data.get("usage_daily", 0)
    usage_monthly = data.get("usage_monthly", 0)

    lines = []
    if limit is not None and limit > 0:
        remaining = max(0, limit - usage)
        lines.append(f"Баланс: ${remaining:.4f} (использовано ${usage:.4f} из ${limit:.4f})")
    else:
        lines.append(f"Использовано всего: ${usage:.4f}")
        if limit is None:
            lines.append("Лимит: неограничен")

    if usage_daily:
        lines.append(f"За сегодня: ${usage_daily:.4f}")
    if usage_monthly:
        lines.append(f"За месяц: ${usage_monthly:.4f}")

    lines.append(f"Тариф: {'бесплатный' if is_free else 'платный'}")

    return "\n".join(lines)
