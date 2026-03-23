"""TCA Theme Engine — 20 themes (10 dark + 10 light) applied programmatically."""
from __future__ import annotations
from typing import Dict, Any

ThemeColors = Dict[str, str]

THEMES: Dict[str, ThemeColors] = {
    # ─── DARK THEMES ───────────────────────────
    "Purple Dark": {
        "bg": "#0D0D0D", "bg2": "#151520", "bg3": "#1a1a2e",
        "fg": "#E5E7EB", "fg2": "#6B7280", "accent": "#8B5CF6",
        "accent2": "#A78BFA", "border": "#2D2D3D",
        "red": "#EF4444", "green": "#10B981", "yellow": "#F59E0B",
        "blue": "#3B82F6", "cyan": "#06B6D4", "kind": "dark",
    },
    "Monokai": {
        "bg": "#272822", "bg2": "#3E3D32", "bg3": "#49483E",
        "fg": "#F8F8F2", "fg2": "#75715E", "accent": "#A6E22E",
        "accent2": "#E6DB74", "border": "#49483E",
        "red": "#F92672", "green": "#A6E22E", "yellow": "#E6DB74",
        "blue": "#66D9EF", "cyan": "#66D9EF", "kind": "dark",
    },
    "Green Terminal": {
        "bg": "#0a0a0a", "bg2": "#0d1f0d", "bg3": "#143314",
        "fg": "#00ff41", "fg2": "#005522", "accent": "#00ff41",
        "accent2": "#33ff99", "border": "#143314",
        "red": "#ff3333", "green": "#00ff41", "yellow": "#ffff00",
        "blue": "#33ff99", "cyan": "#00ff80", "kind": "dark",
    },
    "Blue Ocean": {
        "bg": "#0a0e1a", "bg2": "#0f1729", "bg3": "#1E293B",
        "fg": "#CBD5E1", "fg2": "#475569", "accent": "#3B82F6",
        "accent2": "#60A5FA", "border": "#1E293B",
        "red": "#F87171", "green": "#34D399", "yellow": "#FBBF24",
        "blue": "#3B82F6", "cyan": "#22D3EE", "kind": "dark",
    },
    "Dracula": {
        "bg": "#282A36", "bg2": "#343746", "bg3": "#44475A",
        "fg": "#F8F8F2", "fg2": "#6272A4", "accent": "#BD93F9",
        "accent2": "#FF79C6", "border": "#44475A",
        "red": "#FF5555", "green": "#50FA7B", "yellow": "#F1FA8C",
        "blue": "#8BE9FD", "cyan": "#8BE9FD", "kind": "dark",
    },
    "Nord": {
        "bg": "#2E3440", "bg2": "#3B4252", "bg3": "#434C5E",
        "fg": "#ECEFF4", "fg2": "#4C566A", "accent": "#88C0D0",
        "accent2": "#81A1C1", "border": "#434C5E",
        "red": "#BF616A", "green": "#A3BE8C", "yellow": "#EBCB8B",
        "blue": "#5E81AC", "cyan": "#88C0D0", "kind": "dark",
    },
    "Cyberpunk": {
        "bg": "#0a0a12", "bg2": "#12121f", "bg3": "#1a1a2e",
        "fg": "#F0E6FF", "fg2": "#6a5acd", "accent": "#FF00FF",
        "accent2": "#00FFFF", "border": "#2a1a3e",
        "red": "#FF1744", "green": "#00E676", "yellow": "#FFD600",
        "blue": "#2979FF", "cyan": "#00FFFF", "kind": "dark",
    },
    "Ember": {
        "bg": "#1a0a0a", "bg2": "#2a1515", "bg3": "#3a2020",
        "fg": "#FFE0D0", "fg2": "#8B6F60", "accent": "#FF6B35",
        "accent2": "#FFB347", "border": "#3a2020",
        "red": "#FF4444", "green": "#66BB6A", "yellow": "#FFB347",
        "blue": "#42A5F5", "cyan": "#26C6DA", "kind": "dark",
    },
    "Midnight": {
        "bg": "#0d0d1a", "bg2": "#14142b", "bg3": "#1f1f3d",
        "fg": "#E0E0FF", "fg2": "#5555aa", "accent": "#7C4DFF",
        "accent2": "#B388FF", "border": "#2a2a55",
        "red": "#FF5252", "green": "#69F0AE", "yellow": "#FFD740",
        "blue": "#448AFF", "cyan": "#18FFFF", "kind": "dark",
    },
    "Graphite": {
        "bg": "#1a1a1a", "bg2": "#252525", "bg3": "#333333",
        "fg": "#D4D4D4", "fg2": "#808080", "accent": "#569CD6",
        "accent2": "#9CDCFE", "border": "#404040",
        "red": "#F44747", "green": "#6A9955", "yellow": "#DCDCAA",
        "blue": "#569CD6", "cyan": "#4EC9B0", "kind": "dark",
    },
    # ─── LIGHT THEMES ──────────────────────────
    "Light": {
        "bg": "#FFFFFF", "bg2": "#F3F3F3", "bg3": "#E8E8E8",
        "fg": "#1E1E1E", "fg2": "#6A737D", "accent": "#0366D6",
        "accent2": "#005CC5", "border": "#D1D5DA",
        "red": "#D73A49", "green": "#22863A", "yellow": "#B08800",
        "blue": "#0366D6", "cyan": "#1B7C83", "kind": "light",
    },
    "Solarized Light": {
        "bg": "#FDF6E3", "bg2": "#EEE8D5", "bg3": "#DDD6C1",
        "fg": "#586E75", "fg2": "#93A1A1", "accent": "#268BD2",
        "accent2": "#2AA198", "border": "#D3CBB8",
        "red": "#DC322F", "green": "#859900", "yellow": "#B58900",
        "blue": "#268BD2", "cyan": "#2AA198", "kind": "light",
    },
    "Paper": {
        "bg": "#F5F5F0", "bg2": "#EAEAE5", "bg3": "#DDDDD8",
        "fg": "#333333", "fg2": "#777777", "accent": "#6C5CE7",
        "accent2": "#A29BFE", "border": "#CCCCCC",
        "red": "#E74C3C", "green": "#27AE60", "yellow": "#F39C12",
        "blue": "#3498DB", "cyan": "#1ABC9C", "kind": "light",
    },
    "Ayu Light": {
        "bg": "#FAFAFA", "bg2": "#F0F0F0", "bg3": "#E5E5E5",
        "fg": "#5C6166", "fg2": "#8A9199", "accent": "#FF9940",
        "accent2": "#F2AE49", "border": "#D4D4D4",
        "red": "#F07171", "green": "#86B300", "yellow": "#FF9940",
        "blue": "#399EE6", "cyan": "#4CBF99", "kind": "light",
    },
    "Rose Light": {
        "bg": "#FFF5F5", "bg2": "#FEE2E2", "bg3": "#FECACA",
        "fg": "#4A1C1C", "fg2": "#9B4444", "accent": "#E11D48",
        "accent2": "#FB7185", "border": "#FCA5A5",
        "red": "#E11D48", "green": "#059669", "yellow": "#D97706",
        "blue": "#2563EB", "cyan": "#0891B2", "kind": "light",
    },
    "Mint Light": {
        "bg": "#F0FFF4", "bg2": "#E6FFED", "bg3": "#D1FAE5",
        "fg": "#1A3A2A", "fg2": "#4B8B6E", "accent": "#059669",
        "accent2": "#34D399", "border": "#A7F3D0",
        "red": "#DC2626", "green": "#059669", "yellow": "#D97706",
        "blue": "#2563EB", "cyan": "#0891B2", "kind": "light",
    },
    "Sky Light": {
        "bg": "#F0F9FF", "bg2": "#E0F2FE", "bg3": "#BAE6FD",
        "fg": "#0C2D48", "fg2": "#4B86A8", "accent": "#0284C7",
        "accent2": "#38BDF8", "border": "#7DD3FC",
        "red": "#DC2626", "green": "#16A34A", "yellow": "#CA8A04",
        "blue": "#0284C7", "cyan": "#0891B2", "kind": "light",
    },
    "Lavender Light": {
        "bg": "#FAF5FF", "bg2": "#F3E8FF", "bg3": "#E9D5FF",
        "fg": "#2E1065", "fg2": "#7C3AED", "accent": "#7C3AED",
        "accent2": "#A78BFA", "border": "#C4B5FD",
        "red": "#DC2626", "green": "#16A34A", "yellow": "#CA8A04",
        "blue": "#2563EB", "cyan": "#0891B2", "kind": "light",
    },
    "Sand Light": {
        "bg": "#FEFCF3", "bg2": "#FEF3C7", "bg3": "#FDE68A",
        "fg": "#451A03", "fg2": "#92400E", "accent": "#D97706",
        "accent2": "#F59E0B", "border": "#FCD34D",
        "red": "#DC2626", "green": "#16A34A", "yellow": "#D97706",
        "blue": "#2563EB", "cyan": "#0891B2", "kind": "light",
    },
    "Slate Light": {
        "bg": "#F8FAFC", "bg2": "#F1F5F9", "bg3": "#E2E8F0",
        "fg": "#1E293B", "fg2": "#64748B", "accent": "#475569",
        "accent2": "#94A3B8", "border": "#CBD5E1",
        "red": "#EF4444", "green": "#22C55E", "yellow": "#EAB308",
        "blue": "#3B82F6", "cyan": "#06B6D4", "kind": "light",
    },
}

DARK_THEMES = [n for n, t in THEMES.items() if t["kind"] == "dark"]
LIGHT_THEMES = [n for n, t in THEMES.items() if t["kind"] == "light"]
ALL_THEME_NAMES = list(THEMES.keys())


def get_theme(name: str) -> ThemeColors:
    return THEMES.get(name, THEMES["Purple Dark"])


def apply_theme(app, theme_name: str) -> None:
    """Apply a theme to the TCA app by setting CSS variables on all major widgets."""
    t = get_theme(theme_name)
    # CSS fallback classes for handcrafted theme blocks in tui_app.tcss
    try:
        for cls in ("theme-monokai", "theme-green", "theme-blue"):
            app.remove_class(cls)
        name_low = (theme_name or "").lower()
        if "monokai" in name_low:
            app.add_class("theme-monokai")
        elif "green" in name_low:
            app.add_class("theme-green")
        elif "blue" in name_low:
            app.add_class("theme-blue")
    except Exception:
        pass

    def _s(widget, **kwargs):
        for attr, val in kwargs.items():
            try:
                setattr(widget.styles, attr, val)
            except Exception:
                pass

    try:
        _s(app.screen, background=t["bg"], color=t["fg"])
    except Exception:
        pass

    _apply_recursive(app, t)
    try:
        app.refresh(layout=True)
    except Exception:
        try:
            app.refresh()
        except Exception:
            pass


def _apply_recursive(container, t: ThemeColors) -> None:
    """Walk the widget tree and apply theme colors to all common widgets."""
    from textual.widgets import (
        Header, Static, Button, Input, Label,
        TabbedContent, RichLog, TextArea, Tree, Select,
        Checkbox, Footer,
    )
    from textual.containers import Horizontal, Vertical, VerticalScroll

    try:
        from textual.containers import ScrollableContainer as _ScrollableContainer
    except ImportError:
        _ScrollableContainer = None  # type: ignore[misc, assignment]

    for widget in container.query("*"):
        wid = getattr(widget, "id", "") or ""
        cls_name = widget.__class__.__name__

        if isinstance(widget, Header):
            _set(widget, background=t["bg3"], color=t["accent2"])
        elif wid == "status-bar":
            _set(widget, background=t["bg3"], color=t["fg2"])
        elif wid == "top-bar":
            _set(widget, background=t["bg3"], color=t["fg"])
        elif wid == "top-model-label":
            _set(widget, color=t["accent2"])
        elif wid in ("col-left", "col-center"):
            _set(widget, border_right=("solid", t["border"]), background=t["bg"])
        elif wid == "ai-chat":
            _set(widget, border_left=("solid", t["border"]), background=t["bg"])
        elif wid in ("file-explorer", "code-editor", "version-control", "terminal-panel"):
            _set(widget, border_bottom=("solid", t["border"]), background=t["bg"])
        elif wid in ("resize-left", "resize-right"):
            _set(widget, background=t["border"])

        if isinstance(widget, (Vertical, Horizontal, VerticalScroll)) or (
            _ScrollableContainer is not None and isinstance(widget, _ScrollableContainer)
        ):
            try:
                _set(widget, background=t["bg"])
            except Exception:
                pass
        elif isinstance(widget, TabbedContent):
            _set(widget, background=t["bg"])
        elif cls_name in ("TabPane", "Tabs", "Tab"):
            _set(widget, background=t["bg2"])
            if cls_name == "Tab":
                _set(widget, color=t["fg2"])
        elif isinstance(widget, RichLog):
            _set(widget, background=t["bg"], color=t["fg"])
        elif isinstance(widget, TextArea):
            _set(widget, background=t["bg"], color=t["fg"])
        elif isinstance(widget, Tree):
            _set(widget, background=t["bg"], color=t["fg"])
        elif isinstance(widget, Input):
            _set(widget, background=t["bg2"], color=t["fg"], border=("solid", t["border"]))
        elif isinstance(widget, Button):
            if wid in ("app-exit-btn", "editor-close-btn"):
                _set(widget, background=t["red"], color="#ffffff")
            elif wid and ("term-new-tab" in wid or wid == "send-btn"):
                _set(widget, background=t["accent"], color="#ffffff")
            else:
                _set(widget, background=t["bg2"], color=t["fg"])
        elif isinstance(widget, Select):
            _set(widget, background=t["bg2"], color=t["accent2"])
        elif isinstance(widget, Checkbox):
            _set(widget, background=t["bg"], color=t["fg"])
        elif isinstance(widget, (Label, Static)):
            _set(widget, color=t["fg"])
        elif isinstance(widget, Footer):
            _set(widget, background=t["bg3"], color=t["fg2"])


def _set(widget, **kwargs):
    for attr, val in kwargs.items():
        try:
            setattr(widget.styles, attr, val)
        except Exception:
            pass
