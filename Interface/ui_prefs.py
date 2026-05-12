"""Настройки UI (тема, плотность, синтаксис) в каталоге данных проекта (``.lorne`` / legacy ``.tca``)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_PREFS: Dict[str, Any] = {
    "theme": "Purple Dark",
    # Классический CLI: id пресетов Interface.cli_theme.CLI_THEME_PALETTES (purple, ocean, …).
    "cli_theme": "purple",
    "cli_accent_color": "#8B5CF6",
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
    # Glyph for classic CLI / prompt_toolkit line (Rich markup stripped on save).
    "cli_prompt_glyph": "❯",
    # Custom tools master switch (RAG, planning, interpreter, thinking, etc.).
    "custom_tools_enabled": True,
}


def prefs_path() -> Path:
    try:
        from Agent.path_utils import get_project_root
        from Agent.runtime_paths import project_data_dir

        root = project_data_dir(get_project_root())
    except Exception:
        from Agent.runtime_paths import project_data_dir

        root = project_data_dir()
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
        if "cli_theme" not in data and data.get("theme"):
            from Interface.cli_theme import resolve_cli_theme_name

            out["cli_theme"] = resolve_cli_theme_name(str(data.get("theme")))
        if "cli_accent_color" not in data and data.get("accent_color"):
            out["cli_accent_color"] = str(data["accent_color"])
        return out
    except Exception:
        return dict(DEFAULT_PREFS)


def cli_prompt_prefix_plain() -> str:
    """Plain-text CLI prompt prefix (safe for Rich); ends with a space."""
    try:
        g = str(load_prefs().get("cli_prompt_glyph") or "❯").strip() or "❯"
    except Exception:
        g = "❯"
    g = g.replace("[", "").replace("]", "")[:12]
    return g + (" " if not g.endswith(" ") else "")


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
