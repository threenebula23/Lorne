"""Global UI preferences (theme, density, syntax) persisted under .tca/."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_PREFS: Dict[str, Any] = {
    "theme": "Purple Dark",
    "density": "normal",
    "syntax_theme": "monokai",
    "accent_color": "#8B5CF6",
    # В режиме Agent: подключать Python Playwright (Chromium), если True — см. Settings.
    "playwright_python_enabled": False,
    # В режиме Agent: включать браузерные Node-tools (headless browser layer).
    "browser_tools_enabled": True,
    # Пользовательские модели для селектора (хранятся в проекте).
    "openrouter_custom_models": [],
    "ollama_custom_models": [],
    # Настройки подключения Ollama.
    "ollama_base_url": "http://localhost:11434/v1",
    "ollama_api_key": "",
    "ollama_presets": {
        "default": {
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 40,
            "repeat_penalty": 1.1,
            "num_ctx": 32768,
            "num_predict": 2048,
            "stop": "",
        }
    },
    "ollama_model_settings": {},
    # Creator orchestration (parallel | pipeline | auto).
    "orchestration_mode": "auto",
    # Max parallel workers when creator runs in parallel orchestration.
    "orchestration_max_workers": 4,
    # Research mode knobs — both apply to local + remote.
    "research_max_sources": 6,
    "research_max_rounds": 3,
    "research_deep_fetch": True,
    # Custom tools master switch (RAG, planning, interpreter, thinking, etc.).
    "custom_tools_enabled": True,
}


def prefs_path() -> Path:
    root = Path.cwd() / ".tca"
    root.mkdir(parents=True, exist_ok=True)
    return root / "ui_settings.json"


def load_prefs() -> Dict[str, Any]:
    p = prefs_path()
    if not p.exists():
        return dict(DEFAULT_PREFS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        out = dict(DEFAULT_PREFS)
        out.update({k: v for k, v in data.items() if k in DEFAULT_PREFS})
        return out
    except Exception:
        return dict(DEFAULT_PREFS)


def save_prefs(**kwargs: Any) -> None:
    current = load_prefs()
    for k, v in kwargs.items():
        if k in DEFAULT_PREFS:
            current[k] = v
    try:
        prefs_path().write_text(
            json.dumps(current, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass
