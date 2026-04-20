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
    Button, Checkbox, DirectoryTree, Input, Label, ListItem, ListView,
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


class OpenChatSettings(Message):
    def __init__(self, section: str) -> None:
        super().__init__()
        self.section = section


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
        container = self.query_one("#settings-panel", VerticalScroll)
        for w in list(container.children):
            w.remove()
        container.mount(Label("⚙️ Настройки чата и моделей", classes="settings-title"))
        container.mount(
            Button(
                "🎨 Персонализация\nТема, плотность, подсветка, палитра",
                id="fe-open-settings-personalization",
                variant="primary",
            )
        )
        container.mount(
            Button(
                "🤖 Agents\nПрофиль агента и спец. инструменты",
                id="fe-open-settings-agents",
                variant="default",
            )
        )
        container.mount(
            Button(
                "🔑 OpenRouter\nAPI ключ и добавление моделей",
                id="fe-open-settings-openrouter",
                variant="default",
            )
        )
        container.mount(
            Button(
                "🦙 Ollama\nПодключение, модели, пресеты",
                id="fe-open-settings-ollama",
                variant="default",
            )
        )
        container.mount(Button("✖ Закрыть вкладку настроек", id="fe-open-settings-close", variant="error"))
        container.mount(
            Static(
                "Секция открывается отдельной вкладкой в центре рабочей области.\n"
                "Кнопка «Закрыть вкладку» — в верхней панели этой вкладки."
            )
        )

    @on(DirectoryTree.FileSelected)
    def on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.post_message(FileSelected(event.path))

    # NB: We intentionally do NOT add a handler for
    # ``DirectoryTree.DirectorySelected`` here. Textual's built-in tree
    # already toggles expand/collapse on select, so if we call
    # ``node.expand()``/``node.collapse()`` from our own handler the folder
    # reopens immediately after the user tries to close it (double-toggle).
    # Relying on the default behaviour makes click-to-collapse actually
    # stick.

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
        elif btn_id.startswith("fe-open-settings-"):
            section = btn_id.replace("fe-open-settings-", "", 1).strip().lower()
            if section:
                event.stop()
                self.post_message(OpenChatSettings(section))

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

    @on(Checkbox.Changed, "#fe-playwright-python")
    def on_playwright_python_toggle(self, event: Checkbox.Changed) -> None:
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(playwright_python_enabled=bool(event.value))
            self.notify(
                "Сохранено. В режиме Agent список тулов обновится при следующем сообщении "
                "или сразу при переключении режима.",
            )
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

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
        display.update(Text("Проверка…", style="#6B7280"))

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

from Interface.modal_style import MODAL_SHARED_CSS, apply_accent_to


class _InputDialog(ModalScreen):
    DEFAULT_CSS = MODAL_SHARED_CSS + """
    _InputDialog { align: center middle; }
    #dialog-container {
        width: 88;
        min-width: 40;
        max-width: 96%;
        height: auto;
        max-height: 90%;
    }
    #dialog-title {
        height: auto;
    }
    #dialog-scroll Static { height: auto; }
    #dialog-container Input {
        width: 100%;
        background: #0D0D0D;
        color: #E5E7EB;
        border: solid #2D2D3D;
        margin: 0;
    }
    """

    def __init__(self, prompt: str, callback, default: str = ""):
        super().__init__()
        self._prompt = prompt
        self._callback = callback
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-container", classes="modal-card"):
            yield Label("Введите значение", id="dialog-title", classes="modal-title")
            with VerticalScroll(id="dialog-scroll", classes="modal-scroll"):
                yield Static(Markdown(self._prompt or " "), shrink=False)
            yield Input(value=self._default, id="dialog-input")

    def on_mount(self) -> None:
        apply_accent_to(
            self,
            container_id="dialog-container",
            title_id="dialog-title",
            title_text="Введите значение",
        )
        self.query_one("#dialog-input", Input).focus()

    @on(Input.Submitted, "#dialog-input")
    def on_submit(self, event: Input.Submitted) -> None:
        value = event.value
        self.dismiss()
        self._callback(value)


class _ConfirmDialog(ModalScreen):
    DEFAULT_CSS = MODAL_SHARED_CSS + """
    _ConfirmDialog { align: center middle; }
    #confirm-container {
        width: 88;
        min-width: 40;
        max-width: 96%;
        height: auto;
        max-height: 90%;
    }
    #confirm-title {
        height: auto;
    }
    #confirm-scroll Static { height: auto; }
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
        with Vertical(id="confirm-container", classes="modal-card"):
            yield Label("Подтвердите действие", id="confirm-title", classes="modal-title")
            with VerticalScroll(id="confirm-scroll", classes="modal-scroll"):
                yield Static(Markdown(body or " "), shrink=False)
            with Horizontal(id="confirm-buttons", classes="modal-footer"):
                yield Button("Да", id="confirm-yes", variant="success")
                yield Button("Нет", id="confirm-no", variant="error")

    def on_mount(self) -> None:
        apply_accent_to(
            self,
            container_id="confirm-container",
            title_id="confirm-title",
            title_text="Подтвердите действие",
        )
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

    DEFAULT_CSS = MODAL_SHARED_CSS + """
    _AskUserDialog { align: center middle; }
    #askud-container {
        width: 88;
        min-width: 40;
        max-width: 96%;
        height: auto;
        max-height: 90%;
    }
    #askud-title { height: auto; }
    #askud-scroll Static { height: auto; }
    #askud-custom {
        width: 100%;
        margin: 0 0 1 0;
        background: #0D0D0D;
        color: #E5E7EB;
        border: solid #2D2D3D;
    }
    """

    def __init__(self, question: str, callback) -> None:
        super().__init__()
        self._question = question or ""
        self._callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(id="askud-container", classes="modal-card"):
            yield Label("Ответ агенту", id="askud-title", classes="modal-title")
            with VerticalScroll(id="askud-scroll", classes="modal-scroll"):
                yield Static(Markdown(self._question), shrink=False)
            yield Input(placeholder="Свой ответ (если не подходит Да / Нет)", id="askud-custom")
            with Horizontal(id="askud-buttons", classes="modal-footer"):
                yield Button("Да", id="askud-yes", variant="success")
                yield Button("Нет", id="askud-no", variant="error")
                yield Button("Отправить текст", id="askud-text", variant="default")

    def on_mount(self) -> None:
        apply_accent_to(
            self,
            container_id="askud-container",
            title_id="askud-title",
            title_text="Ответ агенту",
        )
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
    DEFAULT_CSS = MODAL_SHARED_CSS + """
    _ContextMenuDialog { align: center middle; }
    #ctx-menu {
        width: 48;
        height: auto;
        max-height: 22;
        padding: 0;
    }
    #ctx-menu-title {
        background: #1F1B2E;
        padding: 1 1;
        height: auto;
        text-style: bold;
    }
    #ctx-menu ListView {
        background: #12121A;
        height: auto;
        max-height: 16;
        padding: 1 0;
    }
    #ctx-menu ListItem {
        padding: 0 2;
        color: #E5E7EB;
        height: 1;
        margin: 0 0 0 0;
    }
    #ctx-menu ListItem:hover { background: #2A2A3E; }
    #ctx-menu ListItem.--highlight { background: #3B2F55; }
    """

    def __init__(self, title: str, options: list, callback):
        super().__init__()
        self._title = title
        self._options = options
        self._callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(id="ctx-menu", classes="modal-card"):
            yield Static(f"  {self._title}", id="ctx-menu-title")
            yield ListView(id="ctx-menu-list")

    def on_mount(self) -> None:
        apply_accent_to(
            self,
            container_id="ctx-menu",
            title_id="ctx-menu-title",
            title_text=f"  {self._title}",
        )
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
    DEFAULT_CSS = MODAL_SHARED_CSS + """
    _ColorPaletteDialog { align: center middle; }
    #palette-container {
        width: 70;
        height: auto;
        max-height: 18;
    }
    #palette-title { height: auto; }
    #palette-container Horizontal {
        height: auto;
        layout: horizontal;
        margin: 0 0 1 0;
    }
    #palette-container Horizontal Button {
        min-width: 6;
        width: 6;
        height: 3;
        margin: 0 1 0 0;
        border: tall #2D2D3D;
    }
    #palette-cancel {
        min-width: 14;
        height: 3;
        margin: 1 0 0 0;
    }
    """

    def __init__(self, colors_by_id: Dict[str, str], callback):
        super().__init__()
        self._colors = list(colors_by_id.values())
        self._callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-container", classes="modal-card"):
            yield Label("Выберите цвет акцента", id="palette-title", classes="modal-title")
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
        apply_accent_to(
            self,
            container_id="palette-container",
            title_id="palette-title",
            title_text="Выберите цвет акцента",
        )
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
