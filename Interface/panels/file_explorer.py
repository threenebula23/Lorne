"""File Explorer panel — DirectoryTree + Git Staging + Settings tabs."""
from __future__ import annotations

import os
import shutil
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


SKIP_DIRS = {
    ".git", ".idea", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", ".DS_Store", ".tca",
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


class GitCommitRequested(Message):
    def __init__(self, message: str, files: List[str]) -> None:
        super().__init__()
        self.message = message
        self.files = files


class RunFileRequested(Message):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class FileExplorerPanel(Vertical):
    """Left upper panel with 3 tabs: Files, Git Stage, Settings."""

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
        self._staged_files: List[str] = []

    def compose(self) -> ComposeResult:
        with TabbedContent("Files", "Git", "Settings"):
            with TabPane("Files", id="tab-files"):
                with Horizontal(id="file-tree-header"):
                    yield Static(f" 📁 {self._root.name}", id="tree-root-label")
                    yield Button("🔄", id="btn-refresh", classes="header-btn")
                yield FilteredDirectoryTree(str(self._root), id="dir-tree")
                with Horizontal(classes="file-actions"):
                    yield Button("📄 New", id="btn-new", variant="default")
                    yield Button("🗑️ Del", id="btn-del", variant="error")
                    yield Button("✏️ Ren", id="btn-ren", variant="default")
                    yield Button("▶ Run", id="btn-run", variant="warning")
                    yield Button("📎 Ctx", id="btn-ctx", variant="success")
            with TabPane("Git", id="tab-git"):
                yield Vertical(id="git-staging")
            with TabPane("Settings", id="tab-settings"):
                yield VerticalScroll(id="settings-panel")

    def on_mount(self) -> None:
        self._populate_git_staging()
        self._populate_settings()
        self.set_interval(20.0, self._auto_refresh)

    def _auto_refresh(self) -> None:
        try:
            self.query_one("#dir-tree", FilteredDirectoryTree).reload()
        except Exception:
            pass

    def _populate_git_staging(self) -> None:
        container = self.query_one("#git-staging", Vertical)
        try:
            from Agent.git_integration import get_git_manager
            gm = get_git_manager()
            if gm.available:
                status = gm.status_summary()
                files = (
                    status.get("changed", [])
                    + status.get("staged", [])
                    + status.get("untracked", [])
                )
                if files:
                    lv = ListView(id="staged-list")
                    container.mount(lv)
                    for f in files[:30]:
                        lv.append(ListItem(Label(f"  {f}")))
                else:
                    container.mount(Label("  No changes", classes="dim"))
                container.mount(Input(placeholder="Commit message…", id="commit-input"))
                container.mount(Button("Commit", id="commit-btn"))
            else:
                container.mount(Label("  Git not available"))
        except Exception:
            container.mount(Label("  Git not available"))

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

        container.mount(Label("── 📐 Density ── (global)"))
        dens = prefs.get("density", "normal")
        if dens not in ("compact", "normal", "spacious"):
            dens = "normal"
        container.mount(Select(
            [("Compact", "compact"), ("Normal", "normal"), ("Spacious", "spacious")],
            value=dens, id="fe-density-select",
        ))

        container.mount(Label("── 🎨 Syntax Highlighting ── (global)"))
        syn = prefs.get("syntax_theme", "monokai")
        syn_opts = ("monokai", "dracula", "github_dark", "css", "nord")
        if syn not in syn_opts:
            syn = "monokai"
        container.mount(Select(
            [
                ("Monokai", "monokai"),
                ("Dracula", "dracula"),
                ("GitHub Dark", "github_dark"),
                ("VS Dark", "css"),
                ("Nord", "nord"),
            ],
            value=syn, id="fe-syntax-select", allow_blank=False,
        ))

        try:
            apply_theme(self.app, theme_val)
            for d in ("compact", "normal", "spacious"):
                self.app.remove_class(f"density-{d}")
            self.app.add_class(f"density-{dens}")
            for ta in self.app.query(TextArea):
                ta.theme = syn
        except Exception:
            pass

        container.mount(Label("── ⌨️ Hotkeys ──"))
        container.mount(Static(
            "[bold]Ctrl+S[/] Save  [bold]Ctrl+F[/] Find  [bold]Ctrl+W[/] Close Tab\n"
            "[bold]Ctrl+B[/] Sidebar  [bold]Ctrl+T[/] New Term  [bold]F5[/] Run\n"
            "[bold]Ctrl+Shift+X[/] Stop  [bold]Esc[/] Focus Chat\n"
            "[bold]F6/F7[/] Left ±  [bold]F8/F9[/] Right ±  [bold]F10[/] Toggle Term\n"
            "[bold]M[/] Context menu  [bold]Ctrl+Click[/] Right-click (Mac)",
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

    @on(Button.Pressed, "#btn-new")
    def on_new_file(self) -> None:
        self.action_new_file()

    @on(Button.Pressed, "#btn-del")
    def on_delete_file(self) -> None:
        self.action_delete_file()

    @on(Button.Pressed, "#btn-ren")
    def on_rename_file(self) -> None:
        self.action_rename_file()

    @on(Button.Pressed, "#btn-run")
    def on_run_file(self) -> None:
        tree = self.query_one("#dir-tree", FilteredDirectoryTree)
        if tree.cursor_node and tree.cursor_node.data:
            p = tree.cursor_node.data.path
            if p.is_file() and p.suffix in (".py", ".sh", ".js", ".ts"):
                self.post_message(RunFileRequested(p))
            else:
                self.notify("Select a runnable file (.py, .sh, .js)", severity="warning")

    @on(Button.Pressed, "#btn-ctx")
    def on_add_context(self) -> None:
        tree = self.query_one("#dir-tree", FilteredDirectoryTree)
        if tree.cursor_node and tree.cursor_node.data:
            p = tree.cursor_node.data.path
            if p.is_file():
                self.post_message(AddToContext(p))
                self.notify(f"Added to context: {p.name}")

    @on(Button.Pressed, "#btn-refresh")
    def on_refresh(self) -> None:
        self.refresh_tree()
        self.notify("Refreshed")

    @on(Button.Pressed, "#commit-btn")
    def on_commit(self) -> None:
        try:
            inp = self.query_one("#commit-input", Input)
            msg = inp.value.strip()
            if not msg:
                self.notify("Enter a commit message", severity="warning")
                return
            self.post_message(GitCommitRequested(msg, self._staged_files))
            inp.value = ""
            self.notify("Commit created")
        except Exception as e:
            self.notify(f"Commit error: {e}", severity="error")

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
            self.notify(f"Theme: {theme_name}")
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
        self.notify(f"Density: {density}")

    @on(Select.Changed, "#fe-syntax-select")
    def on_syntax_theme_change(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        theme = str(event.value)
        try:
            for ta in self.app.query(TextArea):
                ta.theme = theme
            from Interface.ui_prefs import save_prefs
            save_prefs(syntax_theme=theme)
            self.notify(f"Syntax: {theme}")
        except Exception:
            pass

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
                        from Interface.panels.code_editor import CodeEditorPanel
                        editor = self.app.query_one("#code-editor", CodeEditorPanel)
                        editor.close_file(p)
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
        try:
            self.query_one("#dir-tree", FilteredDirectoryTree).reload()
        except Exception:
            pass


# ─── Modal dialogs ──────────────────────────────────────────

from textual.screen import ModalScreen


class _InputDialog(ModalScreen):
    DEFAULT_CSS = """
    _InputDialog { align: center middle; }
    #dialog-container {
        width: 60; height: auto; max-height: 10;
        background: #1a1a2e; border: solid #8B5CF6; padding: 1 2;
    }
    #dialog-container Label { margin: 0 0 1 0; color: #A78BFA; }
    #dialog-container Input {
        width: 100%; background: #151520; color: #E5E7EB; border: solid #2D2D3D;
    }
    """

    def __init__(self, prompt: str, callback, default: str = ""):
        super().__init__()
        self._prompt = prompt
        self._callback = callback
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-container"):
            yield Label(self._prompt)
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
        width: 60; height: auto; max-height: 12;
        background: #1a1a2e; border: solid #8B5CF6; padding: 1 2;
    }
    #confirm-container Label { margin: 0 0 1 0; color: #A78BFA; }
    #confirm-container .detail { color: #6B7280; margin: 0 0 1 0; }
    #confirm-buttons { layout: horizontal; height: 3; align: center middle; }
    #confirm-buttons Button { min-width: 12; margin: 0 1; }
    """

    def __init__(self, prompt: str, detail: str = "", callback=None):
        super().__init__()
        self._prompt = prompt
        self._detail = detail
        self._callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-container"):
            yield Label(self._prompt)
            if self._detail:
                yield Label(self._detail, classes="detail")
            with Horizontal(id="confirm-buttons"):
                yield Button("✓ Allow", id="confirm-yes", variant="success")
                yield Button("✗ Deny", id="confirm-no", variant="error")

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
