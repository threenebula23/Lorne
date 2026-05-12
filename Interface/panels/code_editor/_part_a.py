"""Панель редактора: TextArea, вкладки, автодополнение, поиск, поддержка .ipynb (часть A)."""
from __future__ import annotations

import json
import io
import re
import subprocess
import sys
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, Input, Label, ListItem, ListView, Static,
    TabbedContent, TabPane, TextArea, RichLog,
)
from textual.message import Message
from rich.text import Text

def _read_notebook_json(path: Path) -> dict:
    """Load .ipynb: UTF-8/BOM, treat empty file as new notebook."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ValueError(f"Cannot read file: {e}") from e

    stripped = raw.strip()
    if not stripped:
        return _minimal_notebook()

    text = raw.decode("utf-8-sig", errors="replace")
    text = text.lstrip("\ufeff")
    text_stripped = text.strip()
    if not text_stripped:
        return _minimal_notebook()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Invalid or empty JSON notebook ({e}). "
            f"If the file is new, save a valid .ipynb from Jupyter or use Lorne to create cells."
        ) from e


def _minimal_notebook() -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        },
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [],
            },
        ],
    }


def _notebook_language(nb_data: dict) -> str:
    ks = (nb_data.get("metadata") or {}).get("kernelspec") or {}
    lang = ks.get("language")
    if lang:
        return str(lang)
    name = str(ks.get("name") or "python3").lower()
    if "python" in name:
        return "python"
    return name or "python"


_LANG_MAP = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".json": "json",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "css", ".sass": "css", ".less": "css",
    ".md": "markdown", ".mdx": "markdown",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".sql": "sql",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".xml": "xml", ".svg": "xml",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "c",
    ".h": "c",
    ".hpp": "c",
    ".cs": "c_sharp",
    ".dart": "dart",
    ".lua": "lua",
    ".pl": "perl",
    ".r": "r",
    ".swift": "swift",
    ".kt": "kotlin",
    ".dockerfile": "dockerfile",
    ".makefile": "make",
}

_PYTHON_KEYWORDS = [
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return",
    "try", "while", "with", "yield",
]

_PYTHON_BUILTINS = [
    "print", "len", "range", "str", "int", "float", "list", "dict",
    "set", "tuple", "bool", "type", "isinstance", "issubclass",
    "hasattr", "getattr", "setattr", "delattr", "property",
    "super", "object", "enumerate", "zip", "map", "filter", "sorted",
    "reversed", "min", "max", "sum", "abs", "round", "any", "all",
    "open", "input", "repr", "hash", "id", "dir", "vars", "globals",
    "locals", "callable", "classmethod", "staticmethod",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "self",
]


def _text_to_ipynb_source(text: str) -> List[str]:
    """Jupyter cell source as list of strings (line-based)."""
    if not text:
        return []
    lines = text.split("\n")
    out: List[str] = []
    for i, ln in enumerate(lines):
        out.append(ln + "\n" if i < len(lines) - 1 else ln)
    return out


def _source_list_to_text(src: Any) -> str:
    if isinstance(src, str):
        return src
    if isinstance(src, list):
        return "".join(src)
    return str(src or "")


class LorneCodeEditor(TextArea):
    """TextArea with keyword/builtin suffix suggestions (→ accept with Right)."""

    def on_key(self, event) -> None:
        # Accept inline completion on Tab (requested UX).
        if getattr(event, "key", "") in ("tab", "right") and getattr(self, "suggestion", ""):
            try:
                self.insert(self.suggestion)
                self.suggestion = ""
                event.stop()
                event.prevent_default()
            except Exception:
                pass
            return
        # Let Textual continue normal key processing via message bubbling;
        # TextArea has no parent `on_key` method to call directly.
        return

    def update_suggestion(self) -> None:
        try:
            self.suggestion = ""
            row, col = self.cursor_location
            lines = self.text.split("\n")
            if row >= len(lines):
                return
            line = lines[row]
            before = line[:col]
            m = re.search(r"([\w_]*)$", before)
            prefix = (m.group(1) if m else "") or ""
            if len(prefix) < 2:
                return
            lang = getattr(self, "language", None)
            if lang is None:
                lang_s = "python"
            elif hasattr(lang, "name"):
                lang_s = str(lang.name).lower()
            else:
                lang_s = str(lang).lower()
            if "markdown" in lang_s or "md" in lang_s:
                return
            candidates: Set[str] = set()
            if "python" in lang_s or not lang_s:
                for kw in _PYTHON_KEYWORDS:
                    if kw.startswith(prefix) and kw != prefix:
                        candidates.add(kw)
                for bi in _PYTHON_BUILTINS:
                    if bi.startswith(prefix) and bi != prefix:
                        candidates.add(bi)
            for w in re.findall(r"\b\w{3,}\b", self.text):
                if w.startswith(prefix) and w != prefix:
                    candidates.add(w)
            if not candidates:
                return
            pick = sorted(candidates)[0]
            if pick.startswith(prefix):
                self.suggestion = pick[len(prefix):]
        except Exception:
            self.suggestion = ""


class NotebookContentDirty(Message):
    """Текст ячейки ноутбука изменён — debounced autosave для вкладки tab_num."""

    bubble = True

    def __init__(self, tab_num: int) -> None:
        super().__init__()
        self.tab_num = tab_num


class NotebookCellTextArea(LorneCodeEditor):
    """Ячейка .ipynb: высота по числу строк кода."""

    _NB_MIN_VISIBLE_LINES = 1
    _NB_MAX_VISIBLE_LINES = 150

    def on_mount(self) -> None:
        self._apply_notebook_height()

    @on(TextArea.Changed)
    def _on_notebook_cell_text_changed(self, _event: TextArea.Changed) -> None:
        self._apply_notebook_height()
        tn = getattr(self, "_nb_tab_for_autosave", None)
        if tn is not None:
            self.post_message(NotebookContentDirty(int(tn)))

    def _apply_notebook_height(self) -> None:
        t = self.text or ""
        line_count = len(t.splitlines()) if t else 0
        n = max(self._NB_MIN_VISIBLE_LINES, line_count)
        n = min(n, self._NB_MAX_VISIBLE_LINES)
        self.styles.height = n


class FileSaved(Message):
    def __init__(self, path: Path, content: str) -> None:
        super().__init__()
        self.path = path
        self.content = content


class RunFileRequested(Message):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class CloseWorkspaceTab(Message):
    def __init__(self, tab_id: str) -> None:
        super().__init__()
        self.tab_id = tab_id


class FileEditorTabPane(Vertical):
    """Single-file editor used inside a workspace tab."""

    BINDINGS = [
        Binding("ctrl+s", "save_file", "Save", show=False),
    ]

    DEFAULT_CSS = """
    FileEditorTabPane {
        height: 1fr;
    }
    #file-tab-toolbar {
        dock: top;
        height: auto;
        min-height: 3;
        layout: horizontal;
        background: #151520;
        padding: 0 0 1 0;
    }
    #file-tab-toolbar Button {
        min-width: 12;
        height: 3;
        margin: 0 1 0 0;
    }
    """

    def __init__(self, path: Path, close_tab_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._path = path.resolve()
        self._close_tab_id = close_tab_id
        safe = close_tab_id.replace("-", "_")
        self._editor_id = f"fte-{safe}"
        suf = self._path.suffix.lower()
        if suf == ".ipynb":
            try:
                nb_data = _read_notebook_json(self._path)
                self._initial_text = json.dumps(nb_data, indent=2, ensure_ascii=False)
                self._lang = "json"
            except Exception as e:
                self._initial_text = f"# Не удалось открыть ipynb как JSON: {e}"
                self._lang = "markdown"
        else:
            try:
                self._initial_text = self._path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                self._initial_text = f"# Cannot read: {e}"
                self._lang = "markdown"
            else:
                self._lang = _LANG_MAP.get(suf, "python")

    def compose(self) -> ComposeResult:
        with Horizontal(id="file-tab-toolbar"):
            yield Button("Сохранить", id="file-tab-save", variant="default")
            yield Button("Закрыть вкладку", id="file-tab-close", variant="error")
        editor = LorneCodeEditor.code_editor(
            self._initial_text, language=self._lang, id=self._editor_id,
        )
        editor.show_line_numbers = True
        yield editor

    def on_mount(self) -> None:
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import SYNTAX_THEME_MAP, ensure_custom_textarea_themes
            ed = self.query_one(f"#{self._editor_id}", LorneCodeEditor)
            ensure_custom_textarea_themes(ed)
            ed.theme = SYNTAX_THEME_MAP.get(
                str(load_prefs().get("syntax_theme", "monokai")), "monokai",
            )
        except Exception:
            pass

    @on(Button.Pressed, "#file-tab-save")
    def _on_save(self) -> None:
        self._save_to_disk()

    @on(Button.Pressed, "#file-tab-run")
    def _on_run(self) -> None:
        self.post_message(RunFileRequested(self._path))

    @on(Button.Pressed, "#file-tab-close")
    def _on_close(self) -> None:
        self.post_message(CloseWorkspaceTab(self._close_tab_id))

    def action_save_file(self) -> None:
        self._save_to_disk()

    def _save_to_disk(self) -> None:
        try:
            ed = self.query_one(f"#{self._editor_id}", LorneCodeEditor)
            text = ed.text
            self._path.write_text(text, encoding="utf-8")
            self.notify(f"Saved: {self._path.name}")
            self.post_message(FileSaved(self._path, text))
        except Exception as e:
            self.notify(f"Save error: {e}", severity="error")


