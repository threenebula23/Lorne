"""Самостоятельные пресеты цветов для классического CLI (Rich + ANSI).

Не зависят от рендера TUI: свои id (purple, ocean, …). Старые имена из TUI
маппятся в ближайший пресет для обратной совместимости.
"""
from __future__ import annotations

from typing import Dict, List

# Ключ: короткий id для /theme и ui_settings.json (cli_theme).
CLI_THEME_PALETTES: Dict[str, Dict[str, str]] = {
    "purple": {
        "fg": "#E5E7EB",
        "fg2": "#6B7280",
        "bg3": "#1a1a2e",
        "accent": "#8B5CF6",
        "accent2": "#A78BFA",
        "border": "#2D2D3D",
        "red": "#EF4444",
        "green": "#10B981",
        "yellow": "#F59E0B",
        "blue": "#3B82F6",
        "cyan": "#06B6D4",
    },
    "monokai": {
        "fg": "#F8F8F2",
        "fg2": "#75715E",
        "bg3": "#272822",
        "accent": "#A6E22E",
        "accent2": "#E6DB74",
        "border": "#49483E",
        "red": "#F92672",
        "green": "#A6E22E",
        "yellow": "#E6DB74",
        "blue": "#66D9EF",
        "cyan": "#66D9EF",
    },
    "ocean": {
        "fg": "#CBD5E1",
        "fg2": "#475569",
        "bg3": "#1E293B",
        "accent": "#3B82F6",
        "accent2": "#60A5FA",
        "border": "#334155",
        "red": "#F87171",
        "green": "#34D399",
        "yellow": "#FBBF24",
        "blue": "#2563EB",
        "cyan": "#22D3EE",
    },
    "dracula": {
        "fg": "#F8F8F2",
        "fg2": "#6272A4",
        "bg3": "#282A36",
        "accent": "#BD93F9",
        "accent2": "#FF79C6",
        "border": "#44475A",
        "red": "#FF5555",
        "green": "#50FA7B",
        "yellow": "#F1FA8C",
        "blue": "#8BE9FD",
        "cyan": "#8BE9FD",
    },
    "nord": {
        "fg": "#ECEFF4",
        "fg2": "#4C566A",
        "bg3": "#2E3440",
        "accent": "#88C0D0",
        "accent2": "#81A1C1",
        "border": "#434C5E",
        "red": "#BF616A",
        "green": "#A3BE8C",
        "yellow": "#EBCB8B",
        "blue": "#5E81AC",
        "cyan": "#8FBCBB",
    },
    "sunset": {
        "fg": "#FFF1F0",
        "fg2": "#A89090",
        "bg3": "#2a1518",
        "accent": "#FF6B35",
        "accent2": "#FFB347",
        "border": "#5c2a2a",
        "red": "#FF4444",
        "green": "#86EFAC",
        "yellow": "#FDE047",
        "blue": "#60A5FA",
        "cyan": "#F472B6",
    },
    "matrix": {
        "fg": "#00FF41",
        "fg2": "#005522",
        "bg3": "#0a120a",
        "accent": "#00FF41",
        "accent2": "#33FF99",
        "border": "#143314",
        "red": "#FF3333",
        "green": "#00FF41",
        "yellow": "#FFFF00",
        "blue": "#33FF99",
        "cyan": "#00FF80",
    },
    "paper": {
        "fg": "#1E1E1E",
        "fg2": "#6A737D",
        "bg3": "#F6F8FA",
        "accent": "#0366D6",
        "accent2": "#005CC5",
        "border": "#D1D5DA",
        "red": "#D73A49",
        "green": "#22863A",
        "yellow": "#B08800",
        "blue": "#0366D6",
        "cyan": "#005CC5",
    },
    # Ниже — дополнительные пресеты с сильным визуальным различием рамок/акцентов.
    "crimson": {
        "fg": "#FEE2E2",
        "fg2": "#9CA3AF",
        "bg3": "#1c0a0c",
        "accent": "#F43F5E",
        "accent2": "#FB7185",
        "border": "#7F1D1D",
        "red": "#EF4444",
        "green": "#34D399",
        "yellow": "#FBBF24",
        "blue": "#60A5FA",
        "cyan": "#F472B6",
    },
    "lime": {
        "fg": "#ECFCC5",
        "fg2": "#65A30D",
        "bg3": "#14200a",
        "accent": "#84CC16",
        "accent2": "#BEF264",
        "border": "#365314",
        "red": "#FB7185",
        "green": "#A3E635",
        "yellow": "#EAB308",
        "blue": "#38BDF8",
        "cyan": "#4ADE80",
    },
    "void": {
        "fg": "#E4E4E7",
        "fg2": "#52525B",
        "bg3": "#09090b",
        "accent": "#A855F7",
        "accent2": "#C084FC",
        "border": "#3F3F46",
        "red": "#F87171",
        "green": "#4ADE80",
        "yellow": "#FACC15",
        "blue": "#818CF8",
        "cyan": "#22D3EE",
    },
    "copper": {
        "fg": "#FFEDD5",
        "fg2": "#A8A29E",
        "bg3": "#1c1410",
        "accent": "#EA580C",
        "accent2": "#FDBA74",
        "border": "#78350F",
        "red": "#EF4444",
        "green": "#84CC16",
        "yellow": "#FDE047",
        "blue": "#38BDF8",
        "cyan": "#FB923C",
    },
    "ice": {
        "fg": "#F0F9FF",
        "fg2": "#64748B",
        "bg3": "#0c1829",
        "accent": "#38BDF8",
        "accent2": "#7DD3FC",
        "border": "#1E3A5F",
        "red": "#F87171",
        "green": "#4ADE80",
        "yellow": "#FDE047",
        "blue": "#0EA5E9",
        "cyan": "#22D3EE",
    },
    "rose": {
        "fg": "#FFF1F2",
        "fg2": "#9F1239",
        "bg3": "#1a0a12",
        "accent": "#E11D48",
        "accent2": "#FB7185",
        "border": "#881337",
        "red": "#FB7185",
        "green": "#86EFAC",
        "yellow": "#FDE047",
        "blue": "#60A5FA",
        "cyan": "#F472B6",
    },
}

DEFAULT_CLI_THEME_ID = "purple"

ALL_CLI_THEME_IDS: List[str] = sorted(CLI_THEME_PALETTES.keys())

# Имена из TUI (Interface.themes.THEMES) → id CLI-пресета.
_TUI_NAME_TO_CLI: Dict[str, str] = {
    "purple dark": "purple",
    "monokai": "monokai",
    "green terminal": "matrix",
    "blue ocean": "ocean",
    "dracula": "dracula",
    "nord": "nord",
    "cyberpunk": "purple",
    "ember": "sunset",
    "midnight": "ocean",
    "graphite": "nord",
    "abyss": "ocean",
    "forest dark": "matrix",
    "light": "paper",
    "solarized light": "paper",
    "paper": "paper",
    "ayu light": "paper",
    "rose light": "sunset",
    "mint light": "paper",
    "sky light": "ocean",
    "lavender light": "purple",
    "sand light": "sunset",
    "slate light": "nord",
    "peach": "sunset",
}


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().replace("_", " ").replace("-", " ").split())


def resolve_cli_theme_name(raw: str) -> str:
    """Вернуть id пресета из CLI_THEME_PALETTES."""
    s = (raw or "").strip()
    if not s:
        return DEFAULT_CLI_THEME_ID

    low = s.lower()
    if low in CLI_THEME_PALETTES:
        return low

    key = _norm(s)
    if key in CLI_THEME_PALETTES:
        return key

    if key in _TUI_NAME_TO_CLI:
        return _TUI_NAME_TO_CLI[key]

    for tui_name, cli_id in _TUI_NAME_TO_CLI.items():
        if key == tui_name or key.replace(" ", "") == tui_name.replace(" ", ""):
            return cli_id

    return DEFAULT_CLI_THEME_ID


def cli_palette(theme_id: str, accent_hex: str = "") -> Dict[str, str]:
    """Палитра для Rich/ANSI. Пользовательский акцент меняет только accent, не accent2 —
    иначе смена темы визуально «пропадает»."""
    tid = resolve_cli_theme_name(theme_id)
    base = dict(CLI_THEME_PALETTES.get(tid, CLI_THEME_PALETTES[DEFAULT_CLI_THEME_ID]))
    ca = (accent_hex or "").strip()
    if ca:
        base["accent"] = ca
        # accent2 остаётся от темы — границы/secondary остаются различимыми между темами
    return base
