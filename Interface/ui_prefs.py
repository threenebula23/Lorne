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
