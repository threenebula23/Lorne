"""File Explorer panel — файлы и настройки."""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.widgets import (
    Button, DirectoryTree, Input, Label, ListItem, ListView,
    Select, Static, TabbedContent, TabPane, TextArea,
)
from textual.message import Message
from rich.text import Text
from rich.markdown import Markdown


SKIP_DIRS = {
    ".git", ".idea", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", ".DS_Store", ".tca",
}

SYNTAX_THEME_MAP = {
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

_FILE_ICONS = {
    ".py": "🐍", ".pyw": "🐍",
    ".js": "📜", ".jsx": "⚛️", ".mjs": "📜",
    ".ts": "🔷", ".tsx": "⚛️",
    ".json": "📋", ".yaml": "📋", ".yml": "📋", ".toml": "📋",
    ".html": "🌐", ".htm": "🌐",
    ".css": "🎨", ".scss": "🎨", ".sass": "🎨",
    ".md": "📝", ".mdx": "📝", ".txt": "📝", ".rst": "📝",
    ".rs": "🦀", ".go": "🔵", ".java": "☕", ".rb": "💎",
    ".sh": "⚙️", ".bash": "⚙️", ".zsh": "⚙️",
    ".sql": "🗃️", ".xml": "📰",
    ".env": "🔒", ".gitignore": "🔒",
    ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️", ".gif": "🖼️", ".svg": "🖼️",
    ".zip": "📦", ".tar": "📦", ".gz": "📦",
    ".pdf": "📕", ".ipynb": "📓",
}


class FilteredDirectoryTree(DirectoryTree):
    def filter_paths(self, paths):
        return [
            p for p in paths
            if p.name not in SKIP_DIRS
            and not (p.name.startswith(".tca_") and p.is_file())
        ]

    def render_label(self, node, base_style, style):
        node_label = node._label.copy()
        node_label.stylize(style)
        path = node.data.path if node.data else None
        if path is None or node._allow_expand:
            icon = "📂 " if node.is_expanded else "📁 "
        else:
            suffix = path.suffix.lower() if path else ""
            name = path.name if path else ""
            if name in (".env", ".gitignore", ".dockerignore"):
                icon = "🔒 "
            else:
                icon = _FILE_ICONS.get(suffix, "📄") + " "
        return Text.assemble((icon, base_style), node_label)


class FileSelected(Message):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class AddToContext(Message):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class RunFileRequested(Message):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class FileExplorerPanel(Vertical):
    """Left upper panel: Files + Settings (API, тема, редактор)."""

    @property
    def project_root(self) -> Path:
        return self._root

    BINDINGS = [
        Binding("n", "new_file", "New File", show=False),
        Binding("d", "delete_file", "Delete", show=False),
        Binding("r", "rename_file", "Rename", show=False),
        Binding("m", "show_menu", "Menu", show=False),
    ]

    def __init__(self, root: Optional[Path] = None, **kwargs):
        super().__init__(**kwargs)
        self._root = root or Path.cwd()
        self._clipboard: Optional[Path] = None
        self._clipboard_cut = False
        self._swatch_map: Dict[str, str] = {}
        self._last_tree_refresh = 0.0

    def compose(self) -> ComposeResult:
        with TabbedContent("Files", "Settings"):
            with TabPane("Files", id="tab-files"):
                with Horizontal(id="file-tree-header"):
                    yield Static(f" 📁 {self._root.name}", id="tree-root-label")
                    yield Button("🔄", id="btn-refresh", classes="header-btn")
                yield FilteredDirectoryTree(str(self._root), id="dir-tree")
                with Horizontal(classes="file-actions"):
                    yield Button("Новый", id="btn-new", variant="default")
                    yield Button("Удалить", id="btn-del", variant="error")
                    yield Button("Переимен.", id="btn-ren", variant="default")
                    yield Button("В контекст", id="btn-ctx", variant="success")
            with TabPane("Settings", id="tab-settings"):
                yield VerticalScroll(id="settings-panel")

    def on_mount(self) -> None:
        self._populate_settings()
        self.set_interval(60.0, self._auto_refresh)

    def _auto_refresh(self) -> None:
        import time
        try:
            tabs = self.query_one(TabbedContent)
            if getattr(tabs, "active", "") != "tab-files":
                return
        except Exception:
            pass
        if (time.time() - self._last_tree_refresh) < 1.0:
            return
        try:
            self.query_one("#dir-tree", FilteredDirectoryTree).reload()
            self._last_tree_refresh = time.time()
        except Exception:
            pass

    def _populate_settings(self) -> None:
        from Interface.ui_prefs import load_prefs
        from Interface.themes import DARK_THEMES, LIGHT_THEMES, ALL_THEME_NAMES, apply_theme

        prefs = load_prefs()
        container = self.query_one("#settings-panel", VerticalScroll)

        container.mount(Label("── 🎨 Theme ── (global)"))
        theme_options = (
            [(f"🌙 {t}", t) for t in DARK_THEMES] +
            [(f"☀️ {t}", t) for t in LIGHT_THEMES]
        )
        theme_val = prefs.get("theme", "Purple Dark")
        if theme_val not in ALL_THEME_NAMES:
            theme_val = "Purple Dark"
        container.mount(Select(
            theme_options, value=theme_val,
            id="fe-theme-select", allow_blank=False,
        ))

        container.mount(Label("── 📐 Размер интерфейса ── (вкладки, кнопки, чат, шрифт в терминале)"))
        dens = prefs.get("density", "normal")
        if dens not in ("compact", "normal", "spacious"):
            dens = "normal"
        container.mount(Select(
            [
                ("Компактный", "compact"),
                ("Обычный", "normal"),
                ("Крупный", "spacious"),
            ],
            value=dens, id="fe-density-select",
        ))

        container.mount(Label("── 🎨 Syntax Highlighting ── (global)"))
        syn = prefs.get("syntax_theme", "monokai")
        syn_opts = tuple(SYNTAX_THEME_MAP.keys())
        if syn not in syn_opts:
            syn = "monokai"
        syn_actual = SYNTAX_THEME_MAP.get(syn, "monokai")
        container.mount(Select(
            [
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
            ],
            value=syn, id="fe-syntax-select", allow_blank=False,
        ))

        container.mount(Label("── 🎨 Accent Color ── (global)"))
        accent_val = prefs.get("accent_color", "#8B5CF6")

        colors = [
            "#8B5CF6", "#A78BFA", "#7C3AED", "#6366F1", "#3B82F6", "#06B6D4", "#10B981", "#22C55E",
            "#84CC16", "#EAB308", "#F59E0B", "#F97316", "#EF4444", "#EC4899", "#D946EF", "#14B8A6",
            "#0EA5E9", "#2563EB", "#4F46E5", "#9333EA", "#DB2777", "#DC2626", "#111827", "#FFFFFF",
        ]
        self._swatch_map.clear()
        for idx, c in enumerate(colors):
            btn_id = f"color-swatch-{idx}"
            self._swatch_map[btn_id] = c

        container.mount(Input(
            value=accent_val,
            placeholder="#RRGGBB",
            id="fe-accent-input",
        ))
        container.mount(Button("🎨 Палитра", id="fe-palette-btn"))

        try:
            from Interface.themes import ensure_custom_textarea_themes
            apply_theme(self.app, theme_val)
            for d in ("compact", "normal", "spacious"):
                self.app.remove_class(f"density-{d}")
            self.app.add_class(f"density-{dens}")
            for ta in self.app.query(TextArea):
                ensure_custom_textarea_themes(ta)
                ta.theme = syn_actual
        except Exception:
            pass

        container.mount(Label("── 🔑 OpenRouter API ──"))
        current_key = os.environ.get("OPENROUTER_API_KEY", "")
        masked = current_key[:8] + "…" if len(current_key) > 8 else current_key
        container.mount(Input(
            value=masked, placeholder="sk-or-…",
            password=True, id="fe-openrouter-key",
        ))
        container.mount(Button("Сохранить ключ", id="fe-save-api-key"))

        container.mount(Label("── 🖥 Локальная модель ──"))
        local_url = os.environ.get("LOCAL_MODEL_URL", "http://localhost:1234/v1")
        container.mount(Input(
            value=local_url, placeholder="http://localhost:1234/v1",
            id="fe-local-model-url",
        ))
        container.mount(Button("Сохранить URL", id="fe-save-local-url"))

        container.mount(Label("── 💰 Баланс OpenRouter ──"))
        container.mount(Button("Проверить баланс", id="fe-check-balance"))
        container.mount(Static("", id="fe-balance-display"))

        container.mount(Label("── 🤖 Своя модель ──"))
        container.mount(Input(placeholder="например openai/gpt-4o", id="fe-custom-model"))
        container.mount(Button("Добавить в список", id="fe-add-model-btn"))

        prof = os.getenv("TCA_PROFILE", "balanced").lower()
        if prof not in ("fast", "balanced", "quality"):
            prof = "balanced"
        container.mount(Label("── 📊 Профиль LLM (TCA_PROFILE) ──"))
        container.mount(Select(
            [("Fast", "fast"), ("Balanced", "balanced"), ("Quality", "quality")],
            value=prof, id="fe-profile-select",
        ))

        container.mount(Label("── ⌨️ Горячие клавиши ──"))
        container.mount(Static(
            "[bold]Ctrl+S[/] Сохранить файл  [bold]Ctrl+F[/] Поиск  [bold]Ctrl+W[/] Закрыть вкладку\n"
            "[bold]Ctrl+B[/] Сайдбар  [bold]F5[/] Запуск файла  [bold]Ctrl+Shift+X[/] Стоп агента\n"
            "[bold]Esc[/] Фокус в чат  [bold]F6/F7[/] Ширина левой колонки\n"
            "[bold]M[/] Меню по файлу  [bold]Ctrl+Click[/] как правый клик (Mac)",
            id="hotkeys-display",
        ))

    @on(DirectoryTree.FileSelected)
    def on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.post_message(FileSelected(event.path))

    @on(DirectoryTree.DirectorySelected)
    def on_dir_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        try:
            node = event.node
            if node.is_expanded:
                node.collapse()
            else:
                node.expand()
        except Exception:
            pass

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("color-swatch-"):
            color = self._swatch_map.get(btn_id)
            if not color:
                return
            self.query_one("#fe-accent-input", Input).value = color
            self._apply_accent_color(color)
            return
        elif btn_id == "btn-new":
            self.action_new_file()
        elif btn_id == "btn-del":
            self.action_delete_file()
        elif btn_id == "btn-ren":
            self.action_rename_file()
        elif btn_id == "btn-ctx":
            tree = self.query_one("#dir-tree", FilteredDirectoryTree)
            if tree.cursor_node and tree.cursor_node.data:
                p = tree.cursor_node.data.path
                if p.is_file():
                    self.post_message(AddToContext(p))
                    self.notify(f"В контекст чата: {p.name}")
        elif btn_id == "btn-refresh":
            self.refresh_tree()
            self.notify("Refreshed")
        elif btn_id == "fe-save-api-key":
            self._fe_save_api_key()
        elif btn_id == "fe-save-local-url":
            self._fe_save_local_url()
        elif btn_id == "fe-check-balance":
            self._fe_check_balance()
        elif btn_id == "fe-add-model-btn":
            self._fe_add_custom_model()
        elif btn_id == "fe-palette-btn":
            def _on_color_selected(selected: Optional[str]) -> None:
                if not selected:
                    return
                self.query_one("#fe-accent-input", Input).value = selected
                self._apply_accent_color(selected)
            self.app.push_screen(_ColorPaletteDialog(self._swatch_map, _on_color_selected))

    @on(Select.Changed, "#fe-theme-select")
    def on_theme_change(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        theme_name = str(event.value)
        try:
            from Interface.themes import apply_theme
            from Interface.ui_prefs import save_prefs
            apply_theme(self.app, theme_name)
            save_prefs(theme=theme_name)
        except Exception as e:
            self.notify(f"Theme error: {e}", severity="error")

    @on(Select.Changed, "#fe-density-select")
    def on_density_change(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        density = str(event.value)
        for d in ("compact", "normal", "spacious"):
            self.app.remove_class(f"density-{d}")
        self.app.add_class(f"density-{density}")
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(density=density)
        except Exception:
            pass

    @on(Select.Changed, "#fe-syntax-select")
    def on_syntax_theme_change(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        theme = str(event.value)
        theme_actual = SYNTAX_THEME_MAP.get(theme, "monokai")
        try:
            from Interface.themes import ensure_custom_textarea_themes
            for ta in self.app.query(TextArea):
                ensure_custom_textarea_themes(ta)
                ta.theme = theme_actual
            from Interface.ui_prefs import save_prefs
            save_prefs(syntax_theme=theme)
        except Exception:
            pass

    def _fe_save_api_key(self) -> None:
        try:
            inp = self.query_one("#fe-openrouter-key", Input)
            key = inp.value.strip()
            if key and not key.endswith("…"):
                os.environ["OPENROUTER_API_KEY"] = key
                env_path = Path.cwd() / ".env"
                _update_env_file(env_path, "OPENROUTER_API_KEY", key)
                self.notify("Ключ сохранён")
            else:
                self.notify("Введите новый ключ", severity="warning")
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    def _fe_save_local_url(self) -> None:
        try:
            inp = self.query_one("#fe-local-model-url", Input)
            url = inp.value.strip()
            if url:
                os.environ["LOCAL_MODEL_URL"] = url
                env_path = Path.cwd() / ".env"
                _update_env_file(env_path, "LOCAL_MODEL_URL", url)
                self.notify(f"URL сохранён")
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    def _fe_check_balance(self) -> None:
        display = self.query_one("#fe-balance-display", Static)
        display.update(Text("Проверка…", style="#F59E0B"))

        def _check():
            try:
                from Agent.llm_provider import fetch_openrouter_credits
                creds = fetch_openrouter_credits()
                if creds:
                    usage = creds.get("usage", 0)
                    limit = creds.get("limit")
                    if limit is not None and limit > 0:
                        remaining = max(0, limit - usage)
                        txt = f"Баланс: ${remaining:.4f} (использовано ${usage:.4f})"
                    else:
                        txt = f"Использовано: ${usage:.4f}"
                    self.app.call_from_thread(display.update, Text(txt, style="#10B981"))
                else:
                    self.app.call_from_thread(display.update, Text("Нет данных", style="#EF4444"))
            except Exception as e:
                self.app.call_from_thread(display.update, Text(f"Ошибка: {e}", style="#EF4444"))

        threading.Thread(target=_check, daemon=True).start()

    def _fe_add_custom_model(self) -> None:
        try:
            inp = self.query_one("#fe-custom-model", Input)
            model_id = inp.value.strip()
            if not model_id:
                return
            inp.value = ""
            chat = self.app.query_one("#ai-chat")
            chat.add_external_model(model_id)
            self.notify(f"Модель добавлена: {model_id}")
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    @on(Select.Changed, "#fe-profile-select")
    def on_fe_profile(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        prof = str(event.value)
        os.environ["TCA_PROFILE"] = prof

        def _work():
            try:
                from Agent.agent import _init_llm
                _init_llm(prof)
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True).start()
        self.notify(f"Профиль: {prof}")

    @on(Input.Changed, "#fe-accent-input")
    def on_accent_color_change(self, event: Input.Changed) -> None:
        color = event.value.strip()
        if not color.startswith("#") or len(color) < 4:
            return
        self._apply_accent_color(color)

    def _apply_accent_color(self, color: str) -> None:
        """Apply and persist accent color."""
        try:
            from Interface.themes import apply_theme
            from Interface.ui_prefs import save_prefs, load_prefs
            prefs = load_prefs()
            save_prefs(accent_color=color)
            apply_theme(self.app, prefs.get("theme", "Purple Dark"))
        except Exception as e:
            self.notify(f"Color error: {e}", severity="error")

    def action_show_menu(self) -> None:
        tree = self.query_one("#dir-tree", FilteredDirectoryTree)
        if tree.cursor_node and tree.cursor_node.data:
            self._show_context_menu(tree.cursor_node.data.path)

    def on_click(self, event) -> None:
        button = getattr(event, "button", 1)
        ctrl = getattr(event, "ctrl", False)
        if button == 3 or (button == 1 and ctrl):
            tree = self.query_one("#dir-tree", FilteredDirectoryTree)
            if tree.cursor_node and tree.cursor_node.data:
                self._show_context_menu(tree.cursor_node.data.path)

    def _show_context_menu(self, path: Path) -> None:
        options = []
        if path.is_file():
            options = [
                ("📄 Open", "open"),
                ("📎 Add to Context", "ctx"),
                ("📋 Copy Path", "copypath"),
                ("✏️ Rename", "rename"),
                ("🗑️ Delete", "delete"),
            ]
            if path.suffix in (".py", ".sh", ".js", ".ts"):
                options.insert(1, ("▶ Run", "run"))
        else:
            options = [
                ("📄 New File Here", "new"),
                ("✏️ Rename", "rename"),
                ("📋 Copy Path", "copypath"),
                ("🗑️ Delete", "delete"),
            ]

        def _handle(choice: str) -> None:
            if choice == "open":
                self.post_message(FileSelected(path))
            elif choice == "ctx":
                self.post_message(AddToContext(path))
            elif choice == "rename":
                self.action_rename_file()
            elif choice == "delete":
                self.action_delete_file()
            elif choice == "run":
                self.post_message(RunFileRequested(path))
            elif choice == "new":
                self.action_new_file()
            elif choice == "copypath":
                self.notify(f"Path: {path}")

        self.app.push_screen(_ContextMenuDialog(path.name, options, _handle))

    def action_new_file(self) -> None:
        tree = self.query_one("#dir-tree", FilteredDirectoryTree)
        node = tree.cursor_node
        if not node or not node.data:
            parent = self._root
        else:
            p = node.data.path
            parent = p if p.is_dir() else p.parent

        def _do_create(name: str) -> None:
            if not name:
                return
            target = parent / name
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            tree.reload()
            self.notify(f"Created: {name}")

        self.app.push_screen(
            _InputDialog("New file/folder name (end with / for folder):", _do_create)
        )

    def action_delete_file(self) -> None:
        tree = self.query_one("#dir-tree", FilteredDirectoryTree)
        node = tree.cursor_node
        if not node or not node.data:
            return
        p = node.data.path
        if p == self._root:
            return

        def _on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                    try:
                        from Interface.panels.workspace_center import WorkspaceCenter
                        ws = self.app.query_one("#workspace-center", WorkspaceCenter)
                        ws.close_path(p)
                    except Exception:
                        pass
                tree.reload()
                self.notify(f"Deleted: {p.name}")
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")

        self.app.push_screen(
            _ConfirmDialog(f"Delete '{p.name}'?", "This cannot be undone.", _on_confirm)
        )

    def action_rename_file(self) -> None:
        tree = self.query_one("#dir-tree", FilteredDirectoryTree)
        node = tree.cursor_node
        if not node or not node.data:
            return
        p = node.data.path

        def _do_rename(new_name: str) -> None:
            if not new_name:
                return
            try:
                new_path = p.parent / new_name
                p.rename(new_path)
                tree.reload()
                self.notify(f"Renamed: {p.name} → {new_name}")
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")

        self.app.push_screen(
            _InputDialog(f"Rename '{p.name}' to:", _do_rename, default=p.name)
        )

    def refresh_tree(self) -> None:
        import time
        if (time.time() - self._last_tree_refresh) < 0.5:
            return
        try:
            self.query_one("#dir-tree", FilteredDirectoryTree).reload()
            self._last_tree_refresh = time.time()
        except Exception:
            pass


def _update_env_file(path: Path, key: str, value: str) -> None:
    lines: List[str] = []
    found = False
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")


# ─── Modal dialogs ──────────────────────────────────────────

from textual.screen import ModalScreen


class _InputDialog(ModalScreen):
    DEFAULT_CSS = """
    _InputDialog { align: center middle; }
    #dialog-container {
        width: 88;
        min-width: 40;
        max-width: 96%;
        height: auto;
        max-height: 90%;
        background: #1a1a2e;
        border: solid #8B5CF6;
        padding: 1 2;
    }
    #dialog-scroll {
        height: auto;
        max-height: 28;
        min-height: 2;
        margin: 0 0 1 0;
        border: solid #2D2D3D;
        background: #12121a;
    }
    #dialog-scroll Static {
        height: auto;
    }
    #dialog-container Input {
        width: 100%;
        background: #151520;
        color: #E5E7EB;
        border: solid #2D2D3D;
    }
    """

    def __init__(self, prompt: str, callback, default: str = ""):
        super().__init__()
        self._prompt = prompt
        self._callback = callback
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-container"):
            with VerticalScroll(id="dialog-scroll"):
                yield Static(Markdown(self._prompt or " "), shrink=False)
            yield Input(value=self._default, id="dialog-input")

    def on_mount(self) -> None:
        self.query_one("#dialog-input", Input).focus()

    @on(Input.Submitted, "#dialog-input")
    def on_submit(self, event: Input.Submitted) -> None:
        value = event.value
        self.dismiss()
        self._callback(value)


class _ConfirmDialog(ModalScreen):
    DEFAULT_CSS = """
    _ConfirmDialog { align: center middle; }
    #confirm-container {
        width: 88;
        min-width: 40;
        max-width: 96%;
        height: auto;
        max-height: 90%;
        background: #1a1a2e;
        border: solid #8B5CF6;
        padding: 1 2;
    }
    #confirm-scroll {
        height: auto;
        max-height: 32;
        min-height: 3;
        margin: 0 0 1 0;
        border: solid #2D2D3D;
        background: #12121a;
    }
    #confirm-scroll Static {
        height: auto;
    }
    #confirm-buttons { layout: horizontal; height: 3; align: center middle; }
    #confirm-buttons Button { min-width: 14; margin: 0 1; }
    """

    def __init__(self, prompt: str, detail: str = "", callback=None):
        super().__init__()
        self._prompt = prompt
        self._detail = detail
        self._callback = callback

    def compose(self) -> ComposeResult:
        body = (self._prompt or "").strip()
        if (self._detail or "").strip():
            body += "\n\n```\n" + (self._detail or "").strip() + "\n```"
        with Vertical(id="confirm-container"):
            with VerticalScroll(id="confirm-scroll"):
                yield Static(Markdown(body or " "), shrink=False)
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", id="confirm-yes", variant="success")
                yield Button("No", id="confirm-no", variant="error")

    def on_mount(self) -> None:
        try:
            self.query_one("#confirm-yes", Button).focus()
        except Exception:
            pass

    @on(Button.Pressed, "#confirm-yes")
    def on_yes(self) -> None:
        self.dismiss()
        if self._callback:
            self._callback(True)

    @on(Button.Pressed, "#confirm-no")
    def on_no(self) -> None:
        self.dismiss()
        if self._callback:
            self._callback(False)


class _AskUserDialog(ModalScreen):
    """Вопрос агенту: Yes / No / свой текст (поле ввода)."""

    DEFAULT_CSS = """
    _AskUserDialog { align: center middle; }
    #askud-container {
        width: 88;
        min-width: 40;
        max-width: 96%;
        height: auto;
        max-height: 90%;
        background: #1a1a2e;
        border: solid #8B5CF6;
        padding: 1 2;
    }
    #askud-scroll {
        height: auto;
        max-height: 30;
        min-height: 3;
        margin: 0 0 1 0;
        border: solid #2D2D3D;
        background: #12121a;
    }
    #askud-scroll Static { height: auto; }
    #askud-custom {
        width: 100%;
        margin: 0 0 1 0;
        background: #151520;
        color: #E5E7EB;
        border: solid #2D2D3D;
    }
    #askud-buttons { layout: horizontal; height: 3; }
    #askud-buttons Button { min-width: 12; margin: 0 1 0 0; }
    """

    def __init__(self, question: str, callback) -> None:
        super().__init__()
        self._question = question or ""
        self._callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(id="askud-container"):
            with VerticalScroll(id="askud-scroll"):
                yield Static(Markdown(self._question), shrink=False)
            yield Input(placeholder="Свой ответ (если не подходит Yes/No)", id="askud-custom")
            with Horizontal(id="askud-buttons"):
                yield Button("Yes", id="askud-yes", variant="success")
                yield Button("No", id="askud-no", variant="error")
                yield Button("Отправить текст", id="askud-text", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#askud-yes", Button).focus()
        except Exception:
            pass

    @on(Button.Pressed, "#askud-yes")
    def on_yes(self) -> None:
        self.dismiss()
        if self._callback:
            self._callback("yes")

    @on(Button.Pressed, "#askud-no")
    def on_no(self) -> None:
        self.dismiss()
        if self._callback:
            self._callback("no")

    @on(Button.Pressed, "#askud-text")
    def on_text(self) -> None:
        raw = (self.query_one("#askud-custom", Input).value or "").strip()
        if not raw:
            self.notify("Введите текст или нажмите Yes / No", severity="warning")
            return
        self.dismiss()
        if self._callback:
            self._callback(raw)


class _ContextMenuDialog(ModalScreen):
    DEFAULT_CSS = """
    _ContextMenuDialog { align: center middle; }
    #ctx-menu {
        width: 40; height: auto; max-height: 16;
        background: #1a1a2e; border: solid #8B5CF6; padding: 0;
    }
    #ctx-menu-title {
        background: #2D2D3D; color: #A78BFA; padding: 0 1; height: 1;
        text-style: bold;
    }
    #ctx-menu ListView { background: #1a1a2e; height: auto; max-height: 12; }
    #ctx-menu ListItem { padding: 0 1; color: #E5E7EB; height: 1; }
    #ctx-menu ListItem:hover { background: #8B5CF6 40%; }
    """

    def __init__(self, title: str, options: list, callback):
        super().__init__()
        self._title = title
        self._options = options
        self._callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(id="ctx-menu"):
            yield Static(f"  {self._title}", id="ctx-menu-title")
            yield ListView(id="ctx-menu-list")

    def on_mount(self) -> None:
        lv = self.query_one("#ctx-menu-list", ListView)
        for label, _action in self._options:
            lv.append(ListItem(Label(label)))
        lv.focus()

    @on(ListView.Selected, "#ctx-menu-list")
    def on_item_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self._options):
            _, action = self._options[idx]
            self.dismiss()
            self._callback(action)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()


class _ColorPaletteDialog(ModalScreen):
    DEFAULT_CSS = """
    _ColorPaletteDialog { align: center middle; }
    #palette-container {
        width: 64; height: auto; max-height: 14;
        background: #1a1a2e; border: solid #8B5CF6; padding: 1 2;
    }
    #palette-grid { height: auto; layout: horizontal; margin: 1 0; }
    #palette-grid Button { min-width: 6; width: 6; height: 3; margin: 0 1 1 0; }
    """

    def __init__(self, colors_by_id: Dict[str, str], callback):
        super().__init__()
        self._colors = list(colors_by_id.values())
        self._callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-container"):
            yield Label("Выберите цвет акцента")
            with Horizontal(id="palette-row-0"):
                for i in range(0, min(8, len(self._colors))):
                    yield Button("  ", id=f"palette-pick-{i}")
            with Horizontal(id="palette-row-1"):
                for i in range(8, min(16, len(self._colors))):
                    yield Button("  ", id=f"palette-pick-{i}")
            with Horizontal(id="palette-row-2"):
                for i in range(16, min(24, len(self._colors))):
                    yield Button("  ", id=f"palette-pick-{i}")
            yield Button("Отмена", id="palette-cancel")

    def on_mount(self) -> None:
        try:
            self.query_one("#palette-cancel", Button).styles.margin = (1, 0, 0, 0)
        except Exception:
            pass
        for i, color in enumerate(self._colors):
            try:
                btn = self.query_one(f"#palette-pick-{i}", Button)
                btn.styles.background = color
            except Exception:
                pass

    @on(Button.Pressed)
    def on_palette_click(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "palette-cancel":
            self.dismiss()
            if self._callback:
                self._callback(None)
            return
        if btn_id.startswith("palette-pick-"):
            idx = int(btn_id.replace("palette-pick-", ""))
            if 0 <= idx < len(self._colors):
                self.dismiss()
                if self._callback:
                    self._callback(self._colors[idx])
