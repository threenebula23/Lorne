"""Константы панели чата: цвета, режимы, наборы имён инструментов."""
from __future__ import annotations

PURPLE = "#8B5CF6"
PURPLE_LIGHT = "#A78BFA"
GRAY = "#6B7280"
GREEN = "#10B981"
RED = "#EF4444"
YELLOW = "#F59E0B"
DIM = "#4B5563"
BLUE = "#3B82F6"
CYAN = "#06B6D4"

MODES = ["Agent", "Ask", "Creator", "Research", "Deep", "Brainer"]
MARKDOWN_SYNTAX_THEME_MAP = {
    "monokai": "monokai",
    "dracula": "dracula",
    "github_dark": "github-dark",
    "github_light": "github-light",
    "vs_dark": "vscode-dark",
    "vscode_dark": "vscode-dark",
    "nord": "nord",
    "one_dark": "one-dark",
    "one_light": "one-light",
    "material": "material",
    "zenburn": "zenburn",
    "solarized_dark": "solarized-dark",
    "solarized_light": "solarized-light",
}

_SYNTAX_OPTIONS = [
    ("Monokai", "monokai"),
    ("Dracula", "dracula"),
    ("GitHub Dark", "github_dark"),
    ("GitHub Light", "github_light"),
    ("VS Dark", "vs_dark"),
    ("Nord", "nord"),
    ("One Dark", "one_dark"),
    ("One Light", "one_light"),
    ("Material", "material"),
    ("Zenburn", "zenburn"),
    ("Solarized Dark", "solarized_dark"),
    ("Solarized Light", "solarized_light"),
]

_ACCENT_COLORS = [
    "#8B5CF6", "#A78BFA", "#7C3AED", "#6366F1", "#3B82F6", "#06B6D4", "#10B981", "#22C55E",
    "#84CC16", "#EAB308", "#F59E0B", "#F97316", "#EF4444", "#EC4899", "#D946EF", "#14B8A6",
    "#0EA5E9", "#2563EB", "#4F46E5", "#9333EA", "#DB2777", "#DC2626", "#111827", "#FFFFFF",
]

_WRITE_TOOLS = frozenset({
    "edit_file", "write_file", "replace_file_lines", "insert_file_lines",
    "create_code_file", "append_code_snippet",
    "code_file_tool",
})

_WEB_TOOLS = frozenset({"web_search", "web_fetch", "web_search_and_read"})

_CHAT_IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})
