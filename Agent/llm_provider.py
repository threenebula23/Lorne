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
    "arcee-ai/":    {"parallel_tool_calls": False, "native_tools": True},
    "stepfun/":     {"parallel_tool_calls": False, "native_tools": True},
    "x-ai/":        {"parallel_tool_calls": False, "native_tools": True},
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


# ─── Popular OpenRouter models (curated) ───────────────────────────
AVAILABLE_MODELS: List[Dict[str, Any]] = [
    # --- free ---
    {"id": "arcee-ai/trinity-large-preview:free",       "name": "Trinity Large",        "ctx": 131_072,    "tier": "free"},
    {"id": "stepfun/step-3.5-flash:free",               "name": "Step 3.5 Flash",        "ctx": 256_000,    "tier": "free"},
    {"id": "qwen/qwen3-235b-a22b-thinking-2507",         "name": "Qwen3 235B Thinking",   "ctx": 131_072,    "tier": "free"},
    # --- paid ---
    {"id": "qwen/qwen3-coder-30b-a3b-instruct",         "name": "Qwen3 Coder 30B",       "ctx": 160_000,    "tier": "paid"},
    {"id": "qwen/qwen3.5-flash-02-23",                  "name": "Qwen3.5 Flash",        "ctx": 1_000_000,    "tier": "paid"},
    {"id": "openai/gpt-oss-120b",                       "name": "GPT OSS 120B",          "ctx": 131_072,    "tier": "paid"},
    {"id": "openai/gpt-5-nano",                         "name": "GPT-5 Nano",             "ctx": 400_000,    "tier": "paid"},
    {"id": "google/gemini-2.5-flash-lite",              "name": "Gemini 2.5 Flash Lite", "ctx": 1_048_576,  "tier": "paid"},
    # --- cheap ---
    {"id": "qwen/qwen3-coder-next",                     "name": "Qwen3 Coder Next",     "ctx": 262_144,    "tier": "cheap"},
    {"id": "qwen/qwen3.5-35b-a3b",                      "name": "Qwen3.5 35B",           "ctx": 262_144,    "tier": "cheap"},
    {"id": "qwen/qwen3.5-plus-02-15",                   "name": "Qwen3.5 Plus",         "ctx": 1_000_000,    "tier": "cheap"},
    {"id": "qwen/qwen3.5-397b-a17b",                    "name": "Qwen3.5 397B",         "ctx": 262_144,    "tier": "cheap"},
    {"id": "openai/gpt-4o-mini",                        "name": "GPT-4o Mini",           "ctx": 128_000,    "tier": "cheap"},
    {"id": "openai/gpt-5-mini",                         "name": "GPT-5 Mini",            "ctx": 400_000,    "tier": "cheap"},
    {"id": "openai/gpt-5.1-codex-mini",                 "name": "GPT-5.1 Codex Mini",     "ctx": 400_000,    "tier": "cheap"},
    {"id": "google/gemini-2.5-flash",                   "name": "Gemini 2.5 Flash",      "ctx": 1_048_576,  "tier": "cheap"},
    {"id": "google/gemini-3-flash-preview",             "name": "Gemini 3 Flash",        "ctx": 1_048_576,  "tier": "cheap"},
    {"id": "x-ai/grok-4.1-fast",                        "name": "Grok 4.1 Fast",         "ctx": 2_000_000,    "tier": "cheap"},
    {"id": "x-ai/grok-code-fast-1",                     "name": "Grok Code Fast",       "ctx": 256_000,    "tier": "cheap"},
    {"id": "deepseek/deepseek-v3.2",                     "name": "DeepSeek V3.2",         "ctx": 163_840,    "tier": "cheap"},
    # --- pro ---
    {"id": "openai/gpt-5.1-codex-max",                  "name": "GPT-5.1 Codex Max",     "ctx": 400_000,    "tier": "pro"},
    {"id": "openai/gpt-5.3-codex",                      "name": "GPT-5.3 Codex",         "ctx": 400_000,    "tier": "pro"},
    {"id": "google/gemini-3.1-pro-preview",             "name": "Gemini 3.1 Pro",         "ctx": 1_048_576,  "tier": "pro"},
    {"id": "anthropic/claude-haiku-4.5",                "name": "Claude Haiku 4.5",       "ctx": 200_000,    "tier": "pro"},
    {"id": "anthropic/claude-sonnet-4.6",               "name": "Claude Sonnet 4.6",     "ctx": 1_000_000,    "tier": "pro"},
    {"id": "anthropic/claude-opus-4.6",                 "name": "Claude Opus 4.6",       "ctx": 1_000_000,    "tier": "pro"},
]


def _ensure_v1_base_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return "http://localhost:11434/v1"
    if u.endswith("/v1"):
        return u
    return u + "/v1"


def _load_ui_model_overrides() -> Dict[str, Any]:
    """Read dynamic model settings from project .tca/ui_settings.json."""
    p = Path.cwd() / ".tca" / "ui_settings.json"
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text("utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {}


def _dedupe_models(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for m in models:
        mid = str(m.get("id") or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(m)
    return out


def get_available_models() -> List[Dict[str, Any]]:
    """Curated models + user-added OpenRouter/Ollama models from UI prefs."""
    prefs = _load_ui_model_overrides()
    merged: List[Dict[str, Any]] = list(AVAILABLE_MODELS)

    for m in (prefs.get("openrouter_custom_models") or []):
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "").strip()
        if not mid:
            continue
        merged.append(
            {
                "id": mid,
                "name": str(m.get("name") or mid),
                "ctx": int(m.get("ctx") or 128_000),
                "tier": str(m.get("tier") or "custom"),
                "source": "openrouter",
            }
        )

    for m in (prefs.get("ollama_custom_models") or []):
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        merged.append(
            {
                "id": f"ollama/{name}",
                "name": str(m.get("label") or f"Ollama · {name}"),
                "ctx": int(m.get("ctx") or 32_768),
                "tier": "local",
                "source": "ollama",
            }
        )

    return _dedupe_models(merged)


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
    return "arcee-ai/trinity-large-preview:free"


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
    wire_model_name = model_name
    model_kwargs: Dict[str, Any] = {}
    extra_body: Optional[Dict[str, Any]] = None
    top_p_value: Optional[float] = None
    if model_name.startswith("ollama/"):
        wire_model_name = model_name.split("/", 1)[1]
        prefs = _load_ui_model_overrides()
        base_url = _ensure_v1_base_url(
            _env(
                "OLLAMA_BASE_URL",
                str(prefs.get("ollama_base_url") or _env("LOCAL_MODEL_URL", "http://localhost:11434/v1")),
            )
        )
        api_key = (
            _env("OLLAMA_API_KEY", str(prefs.get("ollama_api_key") or _env("LOCAL_MODEL_API_KEY", "ollama")))
            or "ollama"
        )
        presets = prefs.get("ollama_presets") if isinstance(prefs.get("ollama_presets"), dict) else {}
        model_map = (
            prefs.get("ollama_model_settings")
            if isinstance(prefs.get("ollama_model_settings"), dict)
            else {}
        )
        raw_cfg = model_map.get(wire_model_name) if isinstance(model_map.get(wire_model_name), dict) else {}
        preset_name = str(raw_cfg.get("preset") or "default")
        preset_cfg = presets.get(preset_name) if isinstance(presets.get(preset_name), dict) else {}
        merged_cfg: Dict[str, Any] = {
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 40,
            "repeat_penalty": 1.1,
            "num_ctx": 32768,
            "num_predict": 2048,
            "stop": "",
        }
        merged_cfg.update({k: v for k, v in preset_cfg.items() if v is not None})
        merged_cfg.update({k: v for k, v in raw_cfg.items() if k != "preset" and v is not None})
        if "temperature" in merged_cfg:
            temperature = float(merged_cfg["temperature"])
            # ChatOpenAI already receives top-level temperature; avoid duplicate validation error.
            merged_cfg.pop("temperature", None)
        if "num_predict" in merged_cfg:
            max_tokens = int(merged_cfg["num_predict"])
            # Keep one source of truth for max generated tokens.
            merged_cfg.pop("num_predict", None)
        if "top_p" in merged_cfg:
            try:
                top_p_value = float(merged_cfg["top_p"])
            except Exception:
                top_p_value = None
            merged_cfg.pop("top_p", None)
        ollama_options: Dict[str, Any] = {}
        for k in ("top_k", "repeat_penalty", "num_ctx"):
            if k in merged_cfg:
                ollama_options[k] = merged_cfg.pop(k)
        stop_raw = str(merged_cfg.get("stop") or "").strip()
        if stop_raw:
            merged_cfg["stop"] = [s.strip() for s in stop_raw.split("|") if s.strip()]
        else:
            merged_cfg.pop("stop", None)
        if ollama_options:
            extra_body = {"options": ollama_options}
        model_kwargs.update(merged_cfg)

    llm_kwargs: Dict[str, Any] = {
        "base_url": base_url,
        "api_key": api_key,
        "model": wire_model_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "request_timeout": 120,
        "max_retries": 3,
    }
    if top_p_value is not None:
        llm_kwargs["top_p"] = top_p_value
    if extra_body:
        llm_kwargs["extra_body"] = extra_body
    if model_kwargs:
        llm_kwargs["model_kwargs"] = model_kwargs

    llm = ChatOpenAI(
        **llm_kwargs,
    )
    return llm, profile_name, model_name


def set_model(model_id: str) -> str:
    """Set model, persist, and rebuild profiles. Returns the model_id."""
    save_model_choice(model_id)
    reload_profiles()
    return model_id


# ─── OpenRouter API ────────────────────────────────────────────────

def fetch_openrouter_credits(api_key: str | None = None) -> Optional[Dict[str, Any]]:
    """Fetch account credits/usage from OpenRouter API.
    Returns dict with 'usage', 'limit', 'is_free_tier', 'rate_limit' or None on error.
    """
    key = (api_key or "").strip() or _env("OPENROUTER_API_KEY", "")
    if not key:
        return None

    url = "https://openrouter.ai/api/v1/auth/key"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", data)
    except Exception:
        return None


def fetch_openrouter_model_metadata(model_id: str, api_key: str = "") -> Optional[Dict[str, Any]]:
    """Fetch one model card from OpenRouter /models by id."""
    key = (api_key or "").strip() or _env("OPENROUTER_API_KEY", "")
    if not key or not model_id:
        return None
    req = urllib.request.Request("https://openrouter.ai/api/v1/models", method="GET")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    rows = data.get("data", [])
    if not isinstance(rows, list):
        return None
    target = (model_id or "").strip().lower()
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or "").strip()
        if rid.lower() == target:
            return row
    return None


def fetch_ollama_models(base_url: str = "", api_key: str = "") -> List[Dict[str, Any]]:
    """Fetch model list from Ollama /api/tags (local or remote)."""
    raw = (base_url or "").strip() or _env("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    base = raw.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    req = urllib.request.Request(base + "/api/tags", method="GET")
    token = (api_key or "").strip() or _env("OLLAMA_API_KEY", "")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    out: List[Dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return out
    for m in (data.get("models") or []):
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        details = m.get("details") if isinstance(m.get("details"), dict) else {}
        out.append(
            {
                "name": name,
                "label": f"Ollama · {name}",
                "ctx": int(m.get("context_length") or details.get("context_length") or 32_768),
                "details": details,
            }
        )
    return out


def _ollama_http_json(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    base_url: str = "",
    api_key: str = "",
    timeout: int = 8,
) -> Optional[Dict[str, Any]]:
    raw = (base_url or "").strip() or _env("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    base = raw.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    url = base + path
    body = None
    headers = {"Content-Type": "application/json"}
    token = (api_key or "").strip() or _env("OLLAMA_API_KEY", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, method=method.upper(), data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_out = resp.read().decode("utf-8", errors="ignore").strip()
            if not raw_out:
                return {}
            data = json.loads(raw_out)
            return data if isinstance(data, dict) else {"data": data}
    except Exception:
        return None


def fetch_ollama_running_models(base_url: str = "", api_key: str = "") -> List[str]:
    """Return currently loaded/running model names from Ollama /api/ps."""
    data = _ollama_http_json("GET", "/api/ps", base_url=base_url, api_key=api_key, timeout=6)
    if not isinstance(data, dict):
        return []
    rows = data.get("models") or []
    out: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if name:
            out.append(name)
    return out


def unload_ollama_models(base_url: str = "", api_key: str = "") -> Dict[str, Any]:
    """Unload all currently running Ollama models (best-effort, no exceptions)."""
    running = fetch_ollama_running_models(base_url=base_url, api_key=api_key)
    unloaded = 0
    failed: List[str] = []
    for name in running:
        ok = _ollama_http_json(
            "POST",
            "/api/generate",
            payload={"model": name, "prompt": "", "stream": False, "keep_alive": 0},
            base_url=base_url,
            api_key=api_key,
            timeout=8,
        )
        if ok is None:
            failed.append(name)
        else:
            unloaded += 1
    return {"running": len(running), "unloaded": unloaded, "failed": failed[:12]}


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
