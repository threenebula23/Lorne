"""Code Editor panel — TextArea with tabs, autocomplete, find/replace, ipynb support."""
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
            f"If the file is new, save a valid .ipynb from Jupyter or use TCA to create cells."
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
    ".c": "c", ".cpp": "cpp", ".h": "cpp", ".hpp": "cpp",
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


class TCACodeEditor(TextArea):
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


class NotebookCellTextArea(TCACodeEditor):
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
            yield Button("Запустить", id="file-tab-run", variant="success")
            yield Button("Закрыть вкладку", id="file-tab-close", variant="error")
        editor = TCACodeEditor.code_editor(
            self._initial_text, language=self._lang, id=self._editor_id,
        )
        editor.show_line_numbers = True
        yield editor

    def on_mount(self) -> None:
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import SYNTAX_THEME_MAP, ensure_custom_textarea_themes
            ed = self.query_one(f"#{self._editor_id}", TCACodeEditor)
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
            ed = self.query_one(f"#{self._editor_id}", TCACodeEditor)
            text = ed.text
            self._path.write_text(text, encoding="utf-8")
            self.notify(f"Saved: {self._path.name}")
            self.post_message(FileSaved(self._path, text))
        except Exception as e:
            self.notify(f"Save error: {e}", severity="error")


class CodeEditorPanel(Vertical):
    """Center upper panel — tabbed code editor with autocomplete and find/replace."""

    BINDINGS = [
        Binding("ctrl+s", "save_file", "Save", show=False),
        Binding("ctrl+f", "toggle_find", "Find", show=False),
        Binding("ctrl+g", "goto_line", "Go to Line", show=False),
        Binding("ctrl+w", "close_tab", "Close Tab", show=False),
        Binding("ctrl+d", "delete_line", "Delete Line", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._open_files: Dict[str, Dict[str, Any]] = {}
        self._tab_counter = 0
        self._autocomplete_items: List[str] = []
        self._find_visible = False
        self._nb_autosave_gen_by_tab: Dict[int, int] = {}

    def _parse_notebook_button_ids(self, btn_id: str, prefix: str) -> Optional[tuple[int, int, int]]:
        """
        Parse IDs like: <prefix>-{tab_num}-{nonce}-{cell_idx}.
        """
        parts = btn_id.replace(prefix, "").split("-")
        if len(parts) < 3:
            return None
        try:
            return int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            return None

    def compose(self) -> ComposeResult:
        with Horizontal(id="editor-toolbar"):
            yield Button("▶ Run", id="editor-run-btn", variant="success")
            yield Button("💾 Save", id="editor-save-btn", variant="default")
            yield Button("✕ Close", id="editor-close-btn", variant="error")
        yield Vertical(id="find-overlay")
        yield TabbedContent(id="editor-tabs")
        yield Static(
            "  Open a file from the explorer\n  or use AI chat",
            classes="editor-empty", id="editor-placeholder",
        )

    def on_mount(self) -> None:
        self._build_find_overlay()

    def _build_find_overlay(self) -> None:
        overlay = self.query_one("#find-overlay", Vertical)
        with self.app.batch_update():
            overlay.mount(Horizontal(
                Input(placeholder="Find…", id="find-input"),
                Button("↑", id="find-prev"),
                Button("↓", id="find-next"),
                Button("×", id="find-close"),
                id="find-row",
            ))
            overlay.mount(Horizontal(
                Input(placeholder="Replace…", id="replace-input"),
                Button("Replace", id="replace-one"),
                Button("All", id="replace-all"),
                id="replace-row",
            ))

    def open_file(self, path: Path) -> None:
        """Open a file in a new tab or focus existing."""
        key = str(path)
        if key in self._open_files:
            tabs = self.query_one("#editor-tabs", TabbedContent)
            tabs.active = self._open_files[key]["tab_id"]
            return

        try:
            placeholder = self.query_one("#editor-placeholder")
            placeholder.display = False
        except Exception:
            pass

        self._tab_counter += 1
        tab_id = f"file-tab-{self._tab_counter}"

        if path.suffix.lower() == ".ipynb":
            self._open_notebook(path, tab_id, key)
        else:
            self._open_text_file(path, tab_id, key)

    def _open_text_file(self, path: Path, tab_id: str, key: str) -> None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            self.notify(f"Cannot read: {e}", severity="error")
            return

        lang = _LANG_MAP.get(path.suffix.lower(), "python")
        tabs = self.query_one("#editor-tabs", TabbedContent)
        pane = TabPane(path.name, id=tab_id)
        tabs.add_pane(pane)

        editor = TCACodeEditor.code_editor(content, language=lang, id=f"editor-{self._tab_counter}")
        editor.show_line_numbers = True
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import SYNTAX_THEME_MAP, ensure_custom_textarea_themes
            ensure_custom_textarea_themes(editor)
            editor.theme = SYNTAX_THEME_MAP.get(str(load_prefs().get("syntax_theme", "monokai")), "monokai")
        except Exception:
            pass
        pane.mount(editor)

        self._open_files[key] = {
            "tab_id": tab_id,
            "path": path,
            "editor_id": f"editor-{self._tab_counter}",
            "original": content,
            "language": lang,
            "is_notebook": False,
        }
        tabs.active = tab_id

    def _open_notebook(self, path: Path, tab_id: str, key: str) -> None:
        """Open a .ipynb file with cell-by-cell rendering."""
        try:
            nb_data = _read_notebook_json(path.resolve())
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        except Exception as e:
            self.notify(f"Cannot open notebook: {e}", severity="error")
            return

        cells = nb_data.get("cells", []) or []
        if not cells:
            nb_data = _minimal_notebook()
            cells = nb_data.get("cells", []) or []

        tabs = self.query_one("#editor-tabs", TabbedContent)
        pane = TabPane(f"📓 {path.name}", id=tab_id)
        tabs.add_pane(pane)

        tab_num = self._tab_counter
        bar = Horizontal(classes="nb-toolbar", id=f"nb-toolbar-{tab_num}")
        pane.mount(bar)
        bar.mount(Button("+ Code", id=f"nb-add-code-{tab_num}", variant="success"))
        bar.mount(Button("+ Markdown", id=f"nb-add-md-{tab_num}", variant="default"))
        bar.mount(Button("💾 Save", id=f"nb-save-{tab_num}", variant="warning"))
        bar.mount(
            Button(
                "↻ Kernel",
                id=f"nb-restart-{tab_num}",
                variant="default",
            ),
        )

        scroll = VerticalScroll(id=f"nb-scroll-{tab_num}")
        pane.mount(scroll)

        self._open_files[key] = {
            "tab_id": tab_id,
            "path": path,
            "editor_id": None,
            "original": None,
            "language": _notebook_language(nb_data),
            "is_notebook": True,
            "nb_data": nb_data,
            "nb_tab_num": tab_num,
            "nb_render_nonce": 0,
            "nb_kernel_globals": {"__name__": "__main__"},
            "nb_exec_counter": 0,
        }
        self._render_notebook_body(key)
        tabs.active = tab_id

    def _render_notebook_body(self, key: str) -> None:
        """Rebuild notebook cell widgets from nb_data."""
        info = self._open_files.get(key)
        if not info or not info.get("is_notebook"):
            return
        tab_num = info["nb_tab_num"]
        scroll = self.query_one(f"#nb-scroll-{tab_num}", VerticalScroll)
        # New nonce every rebuild so widget ids never collide with stale nodes:
        # Textual's remove_children() schedules prune asynchronously (call_next),
        # so old nb-edit-* can still be in the DOM when mounts run.
        nonce = int(info.get("nb_render_nonce", 0)) + 1
        info["nb_render_nonce"] = nonce
        nb_data = info["nb_data"]
        cells = nb_data.get("cells", []) or []
        kernel = _notebook_language(nb_data)

        scroll.remove_children()
        with self.app.batch_update():
            self._mount_notebook_cells(scroll, tab_num, cells, kernel, nonce)
        self._fill_notebook_outputs(
            scroll,
            cells,
            tab_num,
            nonce,
        )

    def _mount_notebook_cells(
        self,
        scroll: VerticalScroll,
        tab_num: int,
        cells: List[dict],
        kernel: str,
        nonce: int,
    ) -> None:
        for ci, cell in enumerate(cells):
            cell_type = cell.get("cell_type", "code")
            source = _source_list_to_text(cell.get("source"))
            exec_count = cell.get("execution_count", "")
            edit_id = f"nb-edit-{tab_num}-{nonce}-{ci}"

            if cell_type == "code":
                scroll.mount(Static(
                    f"[bold #8B5CF6]In [{exec_count or ' '}]:[/]",
                    id=f"nb-in-{tab_num}-{nonce}-{ci}",
                    classes="nb-cell-header",
                ))
                editor = NotebookCellTextArea.code_editor(
                    source,
                    language=kernel,
                    id=edit_id,
                    classes="nb-cell-editor",
                )
                try:
                    from Interface.ui_prefs import load_prefs
                    from Interface.themes import SYNTAX_THEME_MAP, ensure_custom_textarea_themes
                    ensure_custom_textarea_themes(editor)
                    editor.theme = SYNTAX_THEME_MAP.get(str(load_prefs().get("syntax_theme", "monokai")), "monokai")
                except Exception:
                    pass
                editor._nb_tab_for_autosave = tab_num  # noqa: SLF001
                editor.show_line_numbers = True
                scroll.mount(editor)
                scroll.mount(Horizontal(
                    Button(
                        f"▶ Run {ci}",
                        id=f"nb-run-{tab_num}-{nonce}-{ci}",
                        classes="nb-run-btn",
                    ),
                    Button(
                        "Del",
                        id=f"nb-del-{tab_num}-{nonce}-{ci}",
                        variant="error",
                        classes="nb-del-btn",
                    ),
                    classes="nb-cell-actions",
                ))
                scroll.mount(RichLog(
                    id=f"nb-out-{tab_num}-{nonce}-{ci}",
                    wrap=True, markup=True, classes="nb-output",
                ))
            elif cell_type == "markdown":
                scroll.mount(Static("[bold #3B82F6]Markdown[/]", classes="nb-cell-header"))
                md_ed = NotebookCellTextArea.code_editor(
                    source,
                    language="markdown",
                    id=edit_id,
                    classes="nb-cell-editor",
                )
                try:
                    from Interface.ui_prefs import load_prefs
                    from Interface.themes import SYNTAX_THEME_MAP, ensure_custom_textarea_themes
                    ensure_custom_textarea_themes(md_ed)
                    md_ed.theme = SYNTAX_THEME_MAP.get(str(load_prefs().get("syntax_theme", "monokai")), "monokai")
                except Exception:
                    pass
                md_ed._nb_tab_for_autosave = tab_num  # noqa: SLF001
                md_ed.show_line_numbers = False
                scroll.mount(md_ed)
                scroll.mount(Horizontal(
                    Button(
                        "Del",
                        id=f"nb-del-{tab_num}-{nonce}-{ci}",
                        variant="error",
                        classes="nb-del-btn",
                    ),
                    classes="nb-cell-actions",
                ))
            else:
                scroll.mount(Static(
                    f"[bold #6B7280]{cell_type}[/]",
                    classes="nb-cell-header",
                ))
                scroll.mount(Static(source, classes="nb-raw"))

    def _sync_notebook_from_ui(self, key: str) -> None:
        """Copy open editors into nb_data."""
        info = self._open_files.get(key)
        if not info or not info.get("is_notebook"):
            return
        tab_num = info["nb_tab_num"]
        nb_data = info["nb_data"]
        nonce = int(info.get("nb_render_nonce", 0))
        if nonce <= 0:
            return
        for ci, cell in enumerate(nb_data.get("cells", []) or []):
            ct = cell.get("cell_type", "code")
            try:
                if ct == "code":
                    ta = self.query_one(f"#nb-edit-{tab_num}-{nonce}-{ci}", TextArea)
                    cell["source"] = _text_to_ipynb_source(ta.text)
                elif ct == "markdown":
                    ta = self.query_one(f"#nb-edit-{tab_num}-{nonce}-{ci}", TextArea)
                    cell["source"] = _text_to_ipynb_source(ta.text)
            except Exception:
                pass

    def _notebook_key_for_tabnum(self, tab_num: int) -> Optional[str]:
        for k, inf in self._open_files.items():
            if inf.get("is_notebook") and inf.get("nb_tab_num") == tab_num:
                return k
        return None

    def _notebook_add_cell(self, tab_num: int, cell_type: str) -> None:
        key = self._notebook_key_for_tabnum(tab_num)
        if not key:
            return
        self._sync_notebook_from_ui(key)
        info = self._open_files[key]
        nb = info["nb_data"]
        if cell_type == "code":
            nb.setdefault("cells", []).append({
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [],
            })
        else:
            nb.setdefault("cells", []).append({
                "cell_type": "markdown",
                "metadata": {},
                "source": [],
            })
        self._render_notebook_body(key)
        self.notify(f"Added {cell_type} cell")
        self._save_notebook_file(tab_num, silent=True)

    @on(NotebookContentDirty)
    def _on_notebook_content_dirty(self, event: NotebookContentDirty) -> None:
        """Debounced autosave 2s после последнего изменения ячейки (по вкладке)."""
        self._schedule_notebook_autosave(event.tab_num)

    def _schedule_notebook_autosave(self, tab_num: int) -> None:
        g = self._nb_autosave_gen_by_tab.get(tab_num, 0) + 1
        self._nb_autosave_gen_by_tab[tab_num] = g

        def _tick() -> None:
            if self._nb_autosave_gen_by_tab.get(tab_num) != g:
                return
            self._save_notebook_file(tab_num, silent=True)

        self.set_timer(2.0, _tick)

    def _notebook_delete_cell(self, btn_id: str) -> None:
        """Удалить ячейку по id: nb-del-{tab}-{nonce}-{ci}."""
        parts = btn_id.replace("nb-del-", "").split("-")
        if len(parts) < 3:
            return
        try:
            tab_num = int(parts[0])
            cell_idx = int(parts[2])
        except ValueError:
            return
        key = self._notebook_key_for_tabnum(tab_num)
        if not key:
            return
        self._sync_notebook_from_ui(key)
        info = self._open_files[key]
        cells = info["nb_data"].setdefault("cells", [])
        if 0 <= cell_idx < len(cells):
            cells.pop(cell_idx)
            self._render_notebook_body(key)
            self.notify("Cell removed")
            self._save_notebook_file(tab_num, silent=True)

    def _notebook_restart_kernel(self, tab_num: int) -> None:
        """Сброс вывода/счётчиков и состояния in-memory ядра."""
        key = self._notebook_key_for_tabnum(tab_num)
        if not key:
            return
        self._sync_notebook_from_ui(key)
        info = self._open_files[key]
        info["nb_kernel_globals"] = {"__name__": "__main__"}
        info["nb_exec_counter"] = 0
        for cell in info["nb_data"].get("cells", []) or []:
            if cell.get("cell_type") == "code":
                cell["execution_count"] = None
                cell["outputs"] = []
        self._render_notebook_body(key)
        self.notify(
            "Kernel restarted (state, counters and outputs cleared)",
        )
        self._save_notebook_file(tab_num, silent=True)

    def _save_notebook_file(self, tab_num: int, *, silent: bool = False) -> None:
        key = self._notebook_key_for_tabnum(tab_num)
        if not key:
            return
        self._sync_notebook_from_ui(key)
        info = self._open_files[key]
        path = info["path"]
        try:
            text = json.dumps(info["nb_data"], indent=1, ensure_ascii=False)
            path.write_text(text, encoding="utf-8")
            if not silent:
                self.notify(f"Saved notebook: {path.name}")
            self.post_message(FileSaved(path, text))
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    def _fill_notebook_outputs(
        self, scroll, cells, tab_num: int, nonce: int,
    ) -> None:
        """Populate notebook output cells after mount."""
        def _do():
            import time
            time.sleep(0.5)
            for ci, cell in enumerate(cells):
                if cell.get("cell_type") != "code":
                    continue
                outputs = cell.get("outputs", [])
                for out in outputs:
                    text_parts = []
                    if "text" in out:
                        text_parts = out["text"] if isinstance(out["text"], list) else [out["text"]]
                    elif "data" in out:
                        data = out["data"]
                        if "text/plain" in data:
                            txt = data["text/plain"]
                            text_parts = txt if isinstance(txt, list) else [txt]
                    if text_parts:
                        combined = "".join(text_parts)
                        out_id = f"nb-out-{tab_num}-{nonce}-{ci}"
                        def _write(wid=out_id, txt=combined):
                            try:
                                log = scroll.query_one(f"#{wid}", RichLog)
                                log.write(txt[:2000])
                            except Exception:
                                pass
                        try:
                            scroll.app.call_from_thread(_write)
                        except Exception:
                            pass
        threading.Thread(target=_do, daemon=True).start()

    @on(Button.Pressed)
    def on_any_button(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("nb-run-"):
            self._run_notebook_cell(btn_id)
        elif btn_id.startswith("nb-del-"):
            self._notebook_delete_cell(btn_id)
        elif btn_id.startswith("nb-restart-"):
            try:
                self._notebook_restart_kernel(
                    int(btn_id.replace("nb-restart-", "")),
                )
            except ValueError:
                pass
        elif btn_id.startswith("nb-add-code-"):
            try:
                self._notebook_add_cell(int(btn_id.replace("nb-add-code-", "")), "code")
            except ValueError:
                pass
        elif btn_id.startswith("nb-add-md-"):
            try:
                self._notebook_add_cell(int(btn_id.replace("nb-add-md-", "")), "markdown")
            except ValueError:
                pass
        elif btn_id.startswith("nb-save-"):
            try:
                self._save_notebook_file(int(btn_id.replace("nb-save-", "")))
            except ValueError:
                pass
        elif btn_id == "editor-run-btn":
            self._run_current_file()
        elif btn_id == "editor-save-btn":
            self.action_save_file()
        elif btn_id == "editor-close-btn":
            self.action_close_tab()

    def _run_notebook_cell(self, btn_id: str) -> None:
        """Run a single notebook cell preserving notebook state."""
        parsed = self._parse_notebook_button_ids(btn_id, "nb-run-")
        if not parsed:
            return
        tab_num, nonce, cell_idx = parsed
        try:
            editor = self.query_one(
                f"#nb-edit-{tab_num}-{nonce}-{cell_idx}", TextArea,
            )
            code = editor.text
        except Exception:
            return

        out_id = f"nb-out-{tab_num}-{nonce}-{cell_idx}"
        try:
            out_log = self.query_one(f"#{out_id}", RichLog)
        except Exception:
            return

        out_log.clear()
        out_log.write(Text("Running…", style="#F59E0B"))

        key = self._notebook_key_for_tabnum(tab_num)
        if not key:
            return
        self._sync_notebook_from_ui(key)
        info = self._open_files.get(key)
        if not info:
            return

        def _run():
            try:
                stdout_io = io.StringIO()
                stderr_io = io.StringIO()
                g = info.setdefault("nb_kernel_globals", {"__name__": "__main__"})
                exec_error = None
                with redirect_stdout(stdout_io), redirect_stderr(stderr_io):
                    try:
                        compiled = compile(code, f"<cell {cell_idx}>", "exec")
                        exec(compiled, g, g)
                    except Exception:
                        exec_error = traceback.format_exc()

                stdout_text = stdout_io.getvalue()
                stderr_text = stderr_io.getvalue()
                if exec_error:
                    stderr_text = (stderr_text + "\n" + exec_error).strip()

                nb_cells = info.get("nb_data", {}).get("cells", []) or []
                if 0 <= cell_idx < len(nb_cells):
                    c = nb_cells[cell_idx]
                    if c.get("cell_type") == "code":
                        info["nb_exec_counter"] = int(info.get("nb_exec_counter", 0)) + 1
                        c["execution_count"] = info["nb_exec_counter"]
                        outputs: List[Dict[str, Any]] = []
                        if stdout_text:
                            outputs.append(
                                {"name": "stdout", "output_type": "stream", "text": stdout_text}
                            )
                        if stderr_text:
                            outputs.append(
                                {"name": "stderr", "output_type": "stream", "text": stderr_text}
                            )
                        c["outputs"] = outputs

                def _update():
                    out_log.clear()
                    if stdout_text:
                        out_log.write(stdout_text.rstrip())
                    if stderr_text:
                        out_log.write(Text(stderr_text.rstrip(), style="#EF4444"))
                    try:
                        in_lbl = self.query_one(
                            f"#nb-in-{tab_num}-{nonce}-{cell_idx}",
                            Static,
                        )
                        in_lbl.update(
                            f"[bold #8B5CF6]In [{info.get('nb_exec_counter', 0)}]:[/]",
                        )
                    except Exception:
                        pass
                self.app.call_from_thread(_update)
                self._save_notebook_file(tab_num, silent=True)
            except Exception as e:
                self.app.call_from_thread(
                    out_log.write, Text(f"Error: {e}", style="#EF4444")
                )

        threading.Thread(target=_run, daemon=True).start()

    def _run_current_file(self) -> None:
        info = self._get_active_file_info()
        if not info:
            self.notify("No file open", severity="warning")
            return
        p = info["path"]
        if p.suffix in (".py", ".sh", ".js", ".ts"):
            from Interface.panels.file_explorer import RunFileRequested
            self.post_message(RunFileRequested(p))
        else:
            self.notify("Cannot run this file type", severity="warning")

    def _get_active_editor(self) -> Optional[TextArea]:
        tabs = self.query_one("#editor-tabs", TabbedContent)
        active_id = tabs.active
        if not active_id:
            return None
        for info in self._open_files.values():
            if info["tab_id"] == active_id and not info.get("is_notebook"):
                try:
                    return self.query_one(f"#{info['editor_id']}", TextArea)
                except Exception:
                    return None
        return None

    def _get_active_file_info(self) -> Optional[Dict[str, Any]]:
        tabs = self.query_one("#editor-tabs", TabbedContent)
        active_id = tabs.active
        for info in self._open_files.values():
            if info["tab_id"] == active_id:
                return info
        return None

    def action_save_file(self) -> None:
        info = self._get_active_file_info()
        if not info:
            return
        if info.get("is_notebook"):
            tn = info.get("nb_tab_num")
            if tn is not None:
                self._save_notebook_file(int(tn))
            return
        editor = self._get_active_editor()
        if not editor:
            return
        content = editor.text
        path = info["path"]
        try:
            path.write_text(content, encoding="utf-8")
            info["original"] = content
            self.notify(f"Saved: {path.name}")
            self.post_message(FileSaved(path, content))
        except Exception as e:
            self.notify(f"Save error: {e}", severity="error")

    def action_close_tab(self) -> None:
        info = self._get_active_file_info()
        if not info:
            return
        key = str(info["path"])
        tabs = self.query_one("#editor-tabs", TabbedContent)
        try:
            tabs.remove_pane(info["tab_id"])
        except Exception:
            pass
        self._open_files.pop(key, None)
        if not self._open_files:
            try:
                self.query_one("#editor-placeholder").display = True
            except Exception:
                pass

    def close_file(self, path: Path) -> None:
        """Close a tab by file path (e.g. when file is deleted)."""
        key = str(path)
        info = self._open_files.get(key)
        if not info:
            return
        tabs = self.query_one("#editor-tabs", TabbedContent)
        try:
            tabs.remove_pane(info["tab_id"])
        except Exception:
            pass
        self._open_files.pop(key, None)
        if not self._open_files:
            try:
                self.query_one("#editor-placeholder").display = True
            except Exception:
                pass

    def action_toggle_find(self) -> None:
        overlay = self.query_one("#find-overlay", Vertical)
        self._find_visible = not self._find_visible
        if self._find_visible:
            overlay.add_class("visible")
            try:
                self.query_one("#find-input", Input).focus()
            except Exception:
                pass
        else:
            overlay.remove_class("visible")

    def action_goto_line(self) -> None:
        from Interface.panels.file_explorer import _InputDialog

        def _go(line_str: str) -> None:
            if not line_str.isdigit():
                return
            editor = self._get_active_editor()
            if editor:
                line = max(0, int(line_str) - 1)
                editor.cursor_location = (line, 0)

        self.app.push_screen(_InputDialog("Go to line:", _go))

    @on(Button.Pressed, "#find-next")
    def do_find_next(self) -> None:
        self._do_find(forward=True)

    @on(Button.Pressed, "#find-prev")
    def do_find_prev(self) -> None:
        self._do_find(forward=False)

    @on(Button.Pressed, "#find-close")
    def do_find_close(self) -> None:
        self.action_toggle_find()

    @on(Input.Submitted, "#find-input")
    def on_find_submit(self, event: Input.Submitted) -> None:
        self._do_find(forward=True)

    def _do_find(self, forward: bool = True) -> None:
        editor = self._get_active_editor()
        if not editor:
            return
        try:
            query = self.query_one("#find-input", Input).value
        except Exception:
            return
        if not query:
            return

        text = editor.text
        cursor_row, cursor_col = editor.cursor_location
        offset = sum(len(line) + 1 for line in text.splitlines()[:cursor_row]) + cursor_col

        if forward:
            idx = text.find(query, offset + 1)
            if idx == -1:
                idx = text.find(query)
        else:
            idx = text.rfind(query, 0, offset)
            if idx == -1:
                idx = text.rfind(query)

        if idx == -1:
            self.notify("Not found", severity="warning")
            return

        row = text[:idx].count("\n")
        col = idx - text[:idx].rfind("\n") - 1
        editor.cursor_location = (row, col)
        end_col = col + len(query)
        editor.selection = ((row, col), (row, end_col))

    @on(Button.Pressed, "#replace-one")
    def do_replace_one(self) -> None:
        self._do_replace(all_occurrences=False)

    @on(Button.Pressed, "#replace-all")
    def do_replace_all(self) -> None:
        self._do_replace(all_occurrences=True)

    def _do_replace(self, all_occurrences: bool = False) -> None:
        editor = self._get_active_editor()
        if not editor:
            return
        try:
            find_text = self.query_one("#find-input", Input).value
            replace_text = self.query_one("#replace-input", Input).value
        except Exception:
            return
        if not find_text:
            return

        text = editor.text
        if all_occurrences:
            count = text.count(find_text)
            new_text = text.replace(find_text, replace_text)
            editor.load_text(new_text)
            self.notify(f"Replaced {count} occurrences")
        else:
            idx = text.find(find_text)
            if idx == -1:
                self.notify("Not found", severity="warning")
                return
            new_text = text[:idx] + replace_text + text[idx + len(find_text):]
            editor.load_text(new_text)
            self.notify("Replaced 1 occurrence")

    def action_delete_line(self) -> None:
        editor = self._get_active_editor()
        if not editor:
            return
        row, col = editor.cursor_location
        lines = editor.text.split("\n")
        if 0 <= row < len(lines):
            lines.pop(row)
            editor.load_text("\n".join(lines))
            editor.cursor_location = (min(row, len(lines) - 1), 0)

    def on_click(self, event) -> None:
        """Right-click / Ctrl+Click opens context menu in editor."""
        button = getattr(event, "button", 1)
        ctrl = getattr(event, "ctrl", False)
        if button == 3 or (button == 1 and ctrl):
            self._show_editor_context_menu()

    def _show_editor_context_menu(self) -> None:
        editor = self._get_active_editor()
        if not editor:
            return
        from Interface.panels.file_explorer import _ContextMenuDialog
        options = [
            ("📋 Copy Selection", "copy"),
            ("📋 Paste", "paste"),
            ("✂️ Cut Selection", "cut"),
            ("🗑️ Delete Line", "delete_line"),
            ("🔍 Find", "find"),
            ("↕️ Go to Line", "goto"),
            ("📄 Select All", "select_all"),
        ]

        def _handle(choice: str) -> None:
            if choice == "copy":
                sel = editor.selected_text
                if sel:
                    try:
                        import subprocess
                        subprocess.run(["pbcopy"], input=sel, text=True, timeout=2)
                        self.notify("Copied")
                    except Exception:
                        self.notify(f"Selection: {sel[:50]}")
            elif choice == "paste":
                try:
                    import subprocess
                    result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
                    if result.stdout:
                        editor.insert(result.stdout)
                except Exception:
                    self.notify("Paste not available", severity="warning")
            elif choice == "cut":
                sel = editor.selected_text
                if sel:
                    try:
                        import subprocess
                        subprocess.run(["pbcopy"], input=sel, text=True, timeout=2)
                        editor.delete(editor.selection.start, editor.selection.end)
                        self.notify("Cut")
                    except Exception:
                        pass
            elif choice == "delete_line":
                self.action_delete_line()
            elif choice == "find":
                self.action_toggle_find()
            elif choice == "goto":
                self.action_goto_line()
            elif choice == "select_all":
                lines = editor.text.split("\n")
                editor.selection = ((0, 0), (len(lines) - 1, len(lines[-1])))

        self.app.push_screen(_ContextMenuDialog("Editor", options, _handle))

    @on(TextArea.Changed)
    def on_text_changed(self, event: TextArea.Changed) -> None:
        try:
            ta = event.text_area
            if isinstance(ta, TCACodeEditor):
                ta.update_suggestion()
        except Exception:
            pass

    def get_completions(self, prefix: str, language: str = "python") -> List[str]:
        if len(prefix) < 2:
            return []
        editor = self._get_active_editor()
        suggestions: Set[str] = set()

        if language == "python":
            for kw in _PYTHON_KEYWORDS:
                if kw.startswith(prefix):
                    suggestions.add(kw)
            for bi in _PYTHON_BUILTINS:
                if bi.startswith(prefix):
                    suggestions.add(bi)

        if editor:
            words = set(re.findall(r"\b\w{3,}\b", editor.text))
            for w in words:
                if w.startswith(prefix) and w != prefix:
                    suggestions.add(w)
                elif prefix in w and w != prefix:
                    suggestions.add(w)

        return sorted(suggestions)[:15]
