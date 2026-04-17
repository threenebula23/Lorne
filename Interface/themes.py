"""TCA Theme Engine — 20 themes (10 dark + 10 light) applied programmatically."""
from __future__ import annotations
from typing import Dict, Any

from rich.style import Style

ThemeColors = Dict[str, str]

SYNTAX_THEME_MAP: Dict[str, str] = {
    # Built-in + custom registered TextArea themes.
    "monokai": "monokai",
    "dracula": "dracula",
    "github_dark": "github_dark",
    "github_light": "github_light",
    "vs_dark": "vs_dark",
    "vscode_dark": "vscode_dark",
    "nord": "nord",
    "one_dark": "one_dark",
    "one_light": "one_light",
    "material": "material",
    "zenburn": "zenburn",
    "solarized_dark": "solarized_dark",
    "solarized_light": "solarized_light",
}

_CUSTOM_TEXTAREA_THEMES: Dict[str, Dict[str, str]] = {
    "github_dark": {
        "bg": "#0d1117", "fg": "#c9d1d9", "gutter": "#8b949e",
        "keyword": "#ff7b72", "string": "#a5d6ff", "comment": "#8b949e",
        "number": "#79c0ff", "function": "#d2a8ff", "class": "#ffa657",
    },
    "vs_dark": {
        "bg": "#1e1e1e", "fg": "#d4d4d4", "gutter": "#858585",
        "keyword": "#c586c0", "string": "#ce9178", "comment": "#6a9955",
        "number": "#b5cea8", "function": "#dcdcaa", "class": "#4ec9b0",
    },
    "nord": {
        "bg": "#2e3440", "fg": "#d8dee9", "gutter": "#4c566a",
        "keyword": "#81a1c1", "string": "#a3be8c", "comment": "#616e88",
        "number": "#b48ead", "function": "#88c0d0", "class": "#8fbcbb",
    },
    "one_dark": {
        "bg": "#282c34", "fg": "#abb2bf", "gutter": "#5c6370",
        "keyword": "#c678dd", "string": "#98c379", "comment": "#5c6370",
        "number": "#d19a66", "function": "#61afef", "class": "#e5c07b",
    },
    "one_light": {
        "bg": "#fafafa", "fg": "#383a42", "gutter": "#a0a1a7",
        "keyword": "#a626a4", "string": "#50a14f", "comment": "#a0a1a7",
        "number": "#986801", "function": "#4078f2", "class": "#c18401",
    },
    "material": {
        "bg": "#263238", "fg": "#eeffff", "gutter": "#546e7a",
        "keyword": "#c792ea", "string": "#c3e88d", "comment": "#546e7a",
        "number": "#f78c6c", "function": "#82aaff", "class": "#ffcb6b",
    },
    "zenburn": {
        "bg": "#3f3f3f", "fg": "#dcdccc", "gutter": "#7f9f7f",
        "keyword": "#f0dfaf", "string": "#cc9393", "comment": "#7f9f7f",
        "number": "#8cd0d3", "function": "#93e0e3", "class": "#efef8f",
    },
    "solarized_dark": {
        "bg": "#002b36", "fg": "#839496", "gutter": "#586e75",
        "keyword": "#859900", "string": "#2aa198", "comment": "#586e75",
        "number": "#d33682", "function": "#268bd2", "class": "#b58900",
    },
    "solarized_light": {
        "bg": "#fdf6e3", "fg": "#657b83", "gutter": "#93a1a1",
        "keyword": "#859900", "string": "#2aa198", "comment": "#93a1a1",
        "number": "#d33682", "function": "#268bd2", "class": "#b58900",
    },
}


def _register_textarea_theme(widget: Any, name: str, spec: Dict[str, str]) -> None:
    """Register one custom TextArea theme on a widget instance."""
    try:
        from textual._text_area_theme import TextAreaTheme
    except Exception:
        return
    try:
        theme = TextAreaTheme(
            name=name,
            base_style=Style(color=spec["fg"], bgcolor=spec["bg"]),
            gutter_style=Style(color=spec["gutter"], bgcolor=spec["bg"]),
            cursor_line_style=Style(bgcolor=spec["bg"]),
            syntax_styles={
                "keyword": Style(color=spec["keyword"], bold=True),
                "string": Style(color=spec["string"]),
                "comment": Style(color=spec["comment"], italic=True),
                "number": Style(color=spec["number"]),
                "function": Style(color=spec["function"]),
                "function.call": Style(color=spec["function"]),
                "class": Style(color=spec["class"], bold=True),
                "type": Style(color=spec["class"]),
            },
        )
        widget.register_theme(theme)
    except Exception:
        pass


def ensure_custom_textarea_themes(widget: Any) -> None:
    """Register all custom TextArea themes once per widget instance."""
    if getattr(widget, "_tca_custom_syntax_ready", False):
        return
    for name, spec in _CUSTOM_TEXTAREA_THEMES.items():
        _register_textarea_theme(widget, name, spec)
    try:
        setattr(widget, "_tca_custom_syntax_ready", True)
    except Exception:
        pass

THEMES: Dict[str, ThemeColors] = {
    # ─── DARK THEMES ───────────────────────────
    "Purple Dark": {
        "bg": "#0D0D0D", "bg2": "#151520", "bg3": "#1a1a2e",
        "fg": "#E5E7EB", "fg2": "#6B7280", "accent": "#8B5CF6",
        "accent2": "#A78BFA", "border": "#2D2D3D",
        "red": "#EF4444", "green": "#10B981", "yellow": "#F59E0B",
        "blue": "#3B82F6", "cyan": "#06B6D4", "kind": "dark",
        "syntax_theme": "dracula",
    },
    "Monokai": {
        "bg": "#272822", "bg2": "#3E3D32", "bg3": "#49483E",
        "fg": "#F8F8F2", "fg2": "#75715E", "accent": "#A6E22E",
        "accent2": "#E6DB74", "border": "#49483E",
        "red": "#F92672", "green": "#A6E22E", "yellow": "#E6DB74",
        "blue": "#66D9EF", "cyan": "#66D9EF", "kind": "dark",
        "syntax_theme": "monokai",
    },
    "Green Terminal": {
        "bg": "#0a0a0a", "bg2": "#0d1f0d", "bg3": "#143314",
        "fg": "#00ff41", "fg2": "#005522", "accent": "#00ff41",
        "accent2": "#33ff99", "border": "#143314",
        "red": "#ff3333", "green": "#00ff41", "yellow": "#ffff00",
        "blue": "#33ff99", "cyan": "#00ff80", "kind": "dark",
        "syntax_theme": "monokai",
    },
    "Blue Ocean": {
        "bg": "#0a0e1a", "bg2": "#0f1729", "bg3": "#1E293B",
        "fg": "#CBD5E1", "fg2": "#475569", "accent": "#3B82F6",
        "accent2": "#60A5FA", "border": "#1E293B",
        "red": "#F87171", "green": "#34D399", "yellow": "#FBBF24",
        "blue": "#3B82F6", "cyan": "#22D3EE", "kind": "dark",
        "syntax_theme": "nord",
    },
    "Dracula": {
        "bg": "#282A36", "bg2": "#343746", "bg3": "#44475A",
        "fg": "#F8F8F2", "fg2": "#6272A4", "accent": "#BD93F9",
        "accent2": "#FF79C6", "border": "#44475A",
        "red": "#FF5555", "green": "#50FA7B", "yellow": "#F1FA8C",
        "blue": "#8BE9FD", "cyan": "#8BE9FD", "kind": "dark",
        "syntax_theme": "dracula",
    },
    "Nord": {
        "bg": "#2E3440", "bg2": "#3B4252", "bg3": "#434C5E",
        "fg": "#ECEFF4", "fg2": "#4C566A", "accent": "#88C0D0",
        "accent2": "#81A1C1", "border": "#434C5E",
        "red": "#BF616A", "green": "#A3BE8C", "yellow": "#EBCB8B",
        "blue": "#5E81AC", "cyan": "#88C0D0", "kind": "dark",
        "syntax_theme": "nord",
    },
    "Cyberpunk": {
        "bg": "#0a0a12", "bg2": "#12121f", "bg3": "#1a1a2e",
        "fg": "#F0E6FF", "fg2": "#6a5acd", "accent": "#FF00FF",
        "accent2": "#00FFFF", "border": "#2a1a3e",
        "red": "#FF1744", "green": "#00E676", "yellow": "#FFD600",
        "blue": "#2979FF", "cyan": "#00FFFF", "kind": "dark",
        "syntax_theme": "monokai",
    },
    "Ember": {
        "bg": "#1a0a0a", "bg2": "#2a1515", "bg3": "#3a2020",
        "fg": "#FFE0D0", "fg2": "#8B6F60", "accent": "#FF6B35",
        "accent2": "#FFB347", "border": "#3a2020",
        "red": "#FF4444", "green": "#66BB6A", "yellow": "#FFB347",
        "blue": "#42A5F5", "cyan": "#26C6DA", "kind": "dark",
        "syntax_theme": "monokai",
    },
    "Midnight": {
        "bg": "#0d0d1a", "bg2": "#14142b", "bg3": "#1f1f3d",
        "fg": "#E0E0FF", "fg2": "#5555aa", "accent": "#7C4DFF",
        "accent2": "#B388FF", "border": "#2a2a55",
        "red": "#FF5252", "green": "#69F0AE", "yellow": "#FFD740",
        "blue": "#448AFF", "cyan": "#18FFFF", "kind": "dark",
        "syntax_theme": "dracula",
    },
    "Graphite": {
        "bg": "#1a1a1a", "bg2": "#252525", "bg3": "#333333",
        "fg": "#D4D4D4", "fg2": "#808080", "accent": "#569CD6",
        "accent2": "#9CDCFE", "border": "#404040",
        "red": "#F44747", "green": "#6A9955", "yellow": "#DCDCAA",
        "blue": "#569CD6", "cyan": "#4EC9B0", "kind": "dark",
        "syntax_theme": "vscode_dark",
    },
    "Abyss": {
        "bg": "#000c18", "bg2": "#001a30", "bg3": "#002a4a",
        "fg": "#CCE0F0", "fg2": "#406080", "accent": "#007ACC",
        "accent2": "#00A2FF", "border": "#003a60",
        "red": "#FF4B4B", "green": "#00E0A0", "yellow": "#FFCC00",
        "blue": "#007ACC", "cyan": "#00DDEE", "kind": "dark",
        "syntax_theme": "vscode_dark",
    },
    "Forest Dark": {
        "bg": "#0f140f", "bg2": "#1a241a", "bg3": "#2d3d2d",
        "fg": "#E0F0E0", "fg2": "#4d664d", "accent": "#8FB339",
        "accent2": "#B9E769", "border": "#3d523d",
        "red": "#FF5252", "green": "#8FB339", "yellow": "#FBC02D",
        "blue": "#4FC3F7", "cyan": "#4DB6AC", "kind": "dark",
        "syntax_theme": "monokai",
    },
    # ─── LIGHT THEMES ──────────────────────────
    "Light": {
        "bg": "#FFFFFF", "bg2": "#F3F3F3", "bg3": "#E8E8E8",
        "fg": "#1E1E1E", "fg2": "#6A737D", "accent": "#0366D6",
        "accent2": "#005CC5", "border": "#D1D5DA",
        "red": "#D73A49", "green": "#22863A", "yellow": "#B08800",
        "blue": "#0366D6", "cyan": "#1B7C83", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Solarized Light": {
        "bg": "#FDF6E3", "bg2": "#EEE8D5", "bg3": "#DDD6C1",
        "fg": "#586E75", "fg2": "#93A1A1", "accent": "#268BD2",
        "accent2": "#2AA198", "border": "#D3CBB8",
        "red": "#DC322F", "green": "#859900", "yellow": "#B58900",
        "blue": "#268BD2", "cyan": "#2AA198", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Paper": {
        "bg": "#F5F5F0", "bg2": "#EAEAE5", "bg3": "#DDDDD8",
        "fg": "#333333", "fg2": "#777777", "accent": "#6C5CE7",
        "accent2": "#A29BFE", "border": "#CCCCCC",
        "red": "#E74C3C", "green": "#27AE60", "yellow": "#F39C12",
        "blue": "#3498DB", "cyan": "#1ABC9C", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Ayu Light": {
        "bg": "#FAFAFA", "bg2": "#F0F0F0", "bg3": "#E5E5E5",
        "fg": "#5C6166", "fg2": "#8A9199", "accent": "#FF9940",
        "accent2": "#F2AE49", "border": "#D4D4D4",
        "red": "#F07171", "green": "#86B300", "yellow": "#FF9940",
        "blue": "#399EE6", "cyan": "#4CBF99", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Rose Light": {
        "bg": "#FFF5F5", "bg2": "#FEE2E2", "bg3": "#FECACA",
        "fg": "#4A1C1C", "fg2": "#9B4444", "accent": "#E11D48",
        "accent2": "#FB7185", "border": "#FCA5A5",
        "red": "#E11D48", "green": "#059669", "yellow": "#D97706",
        "blue": "#2563EB", "cyan": "#0891B2", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Mint Light": {
        "bg": "#F0FFF4", "bg2": "#E6FFED", "bg3": "#D1FAE5",
        "fg": "#1A3A2A", "fg2": "#4B8B6E", "accent": "#059669",
        "accent2": "#34D399", "border": "#A7F3D0",
        "red": "#DC2626", "green": "#059669", "yellow": "#D97706",
        "blue": "#2563EB", "cyan": "#0891B2", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Sky Light": {
        "bg": "#F0F9FF", "bg2": "#E0F2FE", "bg3": "#BAE6FD",
        "fg": "#0C2D48", "fg2": "#4B86A8", "accent": "#0284C7",
        "accent2": "#38BDF8", "border": "#7DD3FC",
        "red": "#DC2626", "green": "#16A34A", "yellow": "#CA8A04",
        "blue": "#0284C7", "cyan": "#0891B2", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Lavender Light": {
        "bg": "#FAF5FF", "bg2": "#F3E8FF", "bg3": "#E9D5FF",
        "fg": "#2E1065", "fg2": "#7C3AED", "accent": "#7C3AED",
        "accent2": "#A78BFA", "border": "#C4B5FD",
        "red": "#DC2626", "green": "#16A34A", "yellow": "#CA8A04",
        "blue": "#2563EB", "cyan": "#0891B2", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Sand Light": {
        "bg": "#FEFCF3", "bg2": "#FEF3C7", "bg3": "#FDE68A",
        "fg": "#451A03", "fg2": "#92400E", "accent": "#D97706",
        "accent2": "#F59E0B", "border": "#FCD34D",
        "red": "#DC2626", "green": "#16A34A", "yellow": "#D97706",
        "blue": "#2563EB", "cyan": "#0891B2", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Slate Light": {
        "bg": "#F8FAFC", "bg2": "#F1F5F9", "bg3": "#E2E8F0",
        "fg": "#1E293B", "fg2": "#64748B", "accent": "#475569",
        "accent2": "#94A3B8", "border": "#CBD5E1",
        "red": "#EF4444", "green": "#22C55E", "yellow": "#EAB308",
        "blue": "#3B82F6", "cyan": "#06B6D4", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Pistachio": {
        "bg": "#F0FFF0", "bg2": "#E0F0E0", "bg3": "#D0E0D0",
        "fg": "#2D4A2D", "fg2": "#6D8A6D", "accent": "#4CAF50",
        "accent2": "#8BC34A", "border": "#C8E6C9",
        "red": "#E53935", "green": "#43A047", "yellow": "#FBC02D",
        "blue": "#1E88E5", "cyan": "#00ACC1", "kind": "light",
        "syntax_theme": "github_light",
    },
    "Peach": {
        "bg": "#FFF5F0", "bg2": "#FFE0D0", "bg3": "#FFD0C0",
        "fg": "#4A2D2D", "fg2": "#8A6D6D", "accent": "#FF7043",
        "accent2": "#FFAB91", "border": "#FFCCBC",
        "red": "#D84315", "green": "#4CAF50", "yellow": "#FBC02D",
        "blue": "#1E88E5", "cyan": "#00ACC1", "kind": "light",
        "syntax_theme": "github_light",
    },
}

DARK_THEMES = [n for n, t in THEMES.items() if t["kind"] == "dark"]
LIGHT_THEMES = [n for n, t in THEMES.items() if t["kind"] == "light"]
ALL_THEME_NAMES = list(THEMES.keys())


def get_theme(name: str) -> ThemeColors:
    return THEMES.get(name, THEMES["Purple Dark"])


def apply_theme(app, theme_name: str) -> None:
    """Apply a theme to the TCA app by setting CSS variables on all major widgets."""
    from .ui_prefs import load_prefs
    prefs = load_prefs()
    custom_accent = prefs.get("accent_color")
    syntax_pref = str(prefs.get("syntax_theme", "")).strip()

    t = dict(get_theme(theme_name))
    if custom_accent:
        t["accent"] = custom_accent
        # Generate a slightly lighter version for accent2 if we wanted, 
        # but for now just use the same or keep original if it looks okay.
        # Actually, let's just use the custom accent for both if it's set.
        t["accent2"] = custom_accent 
    if syntax_pref:
        t["syntax_theme"] = SYNTAX_THEME_MAP.get(
            syntax_pref,
            t.get("syntax_theme", "monokai"),
        )
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
        elif wid in ("col-left",):
            _set(widget, border_right=("solid", t["border"]), background=t["bg"])
        elif wid == "workspace-center":
            _set(widget, background=t["bg"])
        elif wid in ("file-explorer", "active-agents"):
            _set(widget, border_bottom=("solid", t["border"]), background=t["bg"])

        if isinstance(widget, (Vertical, Horizontal, VerticalScroll)) or (
            _ScrollableContainer is not None and isinstance(widget, _ScrollableContainer)
        ):
            try:
                _set(
                    widget,
                    background=t["bg"],
                    scrollbar_color=t["accent"],
                    scrollbar_background=t["bg3"],
                )
            except Exception:
                pass
        elif isinstance(widget, TabbedContent):
            _set(widget, background=t["bg"])
            try:
                # Textual 0.50+ TabbedContent has a sub-widget for tabs
                for sub in widget.query("Tabs"):
                    _set(sub, background=t["bg2"])
            except Exception:
                pass
        elif cls_name in ("TabPane", "Tabs", "Tab"):
            _set(widget, background=t["bg2"])
            if cls_name == "Tab":
                _set(widget, color=t["fg2"])
                # We can't easily set the underline color via styles on Tab, 
                # but we can set the active color.
        elif isinstance(widget, RichLog):
            _set(
                widget,
                background=t["bg"],
                color=t["fg"],
                scrollbar_color=t["accent"],
                scrollbar_background=t["bg3"],
            )
        elif isinstance(widget, TextArea):
            _set(
                widget,
                background=t["bg"],
                color=t["fg"],
                scrollbar_color=t["accent"],
                scrollbar_background=t["bg3"],
            )
            try:
                ensure_custom_textarea_themes(widget)
                if "syntax_theme" in t:
                    widget.theme = t["syntax_theme"]
            except Exception:
                pass
        elif isinstance(widget, Tree):
            _set(
                widget,
                background=t["bg"],
                color=t["fg"],
                scrollbar_color=t["accent"],
                scrollbar_background=t["bg3"],
            )
        elif isinstance(widget, Input):
            _set(widget, background=t["bg2"], color=t["fg"], border=("solid", t["border"]))
            if widget.has_focus:
                _set(widget, border=("solid", t["accent"]))
        elif isinstance(widget, Button):
            classes = str(getattr(widget, "classes", ""))
            if wid.startswith("color-swatch-") or "color-swatch" in classes:
                # Keep palette swatch colors untouched.
                continue
            if wid in ("app-exit-btn", "editor-close-btn"):
                _set(widget, background=t["red"], color="#ffffff")
            elif wid and ("term-new-tab" in wid or wid == "send-btn" or "run" in wid):
                _set(widget, background=t["accent"], color="#ffffff")
            else:
                _set(widget, background=t["bg2"], color=t["fg"])
        elif isinstance(widget, Select):
            _set(widget, background=t["bg2"], color=t["accent2"])
        elif isinstance(widget, Checkbox):
            _set(widget, background=t["bg"], color=t["fg"])
        elif isinstance(widget, (Label, Static)):
            if "accent" in (wid or "").lower():
                _set(widget, color=t["accent"])
            else:
                _set(widget, color=t["fg"])
        elif isinstance(widget, Footer):
            _set(widget, background=t["bg3"], color=t["fg2"])


def _set(widget, **kwargs):
    for attr, val in kwargs.items():
        try:
            setattr(widget.styles, attr, val)
        except Exception:
            pass
