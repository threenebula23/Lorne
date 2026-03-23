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
    Button, Checkbox, DirectoryTree, Input, Label, ListItem, ListView,
    Select, Static, TabbedContent, TabPane, TextArea,
)
from textual.message import Message
from rich.text import Text


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
        self._swatch_map: Dict[str, str] = {}
        self._last_tree_refresh = 0.0

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
                yield VerticalScroll(id="git-staging")
            with TabPane("Settings", id="tab-settings"):
                yield VerticalScroll(id="settings-panel")

    def on_mount(self) -> None:
        self._populate_git_staging()
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

    def _populate_git_staging(self) -> None:
        container = self.query_one("#git-staging", VerticalScroll)
        container.remove_children()
        self._staged_files.clear()
        try:
            from Agent.git_integration import get_git_manager
            gm = get_git_manager()
            if gm.available:
                status = gm.status_summary()
                files_raw = (
                    status.get("changed", [])
                    + status.get("staged", [])
                    + status.get("untracked", [])
                )
                files = []
                seen = set()
                for f in files_raw:
                    if f not in seen:
                        seen.add(f)
                        files.append(f)
                if files:
                    container.mount(Static("── Git Staging ──", classes="staging-header"))
                    for i, f in enumerate(files):
                        cat = "M"
                        if f in status.get("untracked", []):
                            cat = "?"
                        elif f in status.get("staged", []):
                            cat = "S"
                        is_selected = cat == "S"
                        if is_selected:
                            self._staged_files.append(f)
                        marker = "✓" if is_selected else "○"
                        cb = Checkbox(
                            f"{marker} [{cat}] {f}",
                            value=is_selected,
                            id=f"fe-stage-file-{i}",
                            classes="git-stage-checkbox",
                        )
                        cb._file_path = f
                        cb._cat = cat
                        container.mount(cb)
                else:
                    container.mount(Label("  No changes", classes="dim"))
                container.mount(Input(placeholder="Commit message…", id="commit-input"))
                container.mount(Button("Commit", id="commit-btn"))
            else:
                container.mount(Label("  Git not available"))
        except Exception:
            container.mount(Label("  Git not available"))

    @on(Checkbox.Changed, ".git-stage-checkbox")
    def on_git_stage_toggle(self, event: Checkbox.Changed) -> None:
        cb = event.checkbox
        file_path = getattr(cb, "_file_path", None)
        cat = getattr(cb, "_cat", "M")
        if not file_path:
            return
        try:
            from Agent.git_integration import get_git_manager
            gm = get_git_manager()
            if gm.available and gm.repo:
                if event.value:
                    gm.repo.index.add([file_path])
                else:
                    gm.repo.git.reset("HEAD", "--", file_path)
        except Exception:
            pass
        if event.value:
            if file_path not in self._staged_files:
                self._staged_files.append(file_path)
            cb.label = f"✓ [{cat}] {file_path}"
        else:
            self._staged_files = [f for f in self._staged_files if f != file_path]
            cb.label = f"○ [{cat}] {file_path}"

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
        elif btn_id == "btn-run":
            tree = self.query_one("#dir-tree", FilteredDirectoryTree)
            if tree.cursor_node and tree.cursor_node.data:
                p = tree.cursor_node.data.path
                if p.is_file() and p.suffix in (".py", ".sh", ".js", ".ts"):
                    self.post_message(RunFileRequested(p))
                else:
                    self.notify("Select a runnable file (.py, .sh, .js)", severity="warning")
        elif btn_id == "btn-ctx":
            tree = self.query_one("#dir-tree", FilteredDirectoryTree)
            if tree.cursor_node and tree.cursor_node.data:
                p = tree.cursor_node.data.path
                if p.is_file():
                    self.post_message(AddToContext(p))
                    self.notify(f"Added to context: {p.name}")
        elif btn_id == "btn-refresh":
            self.refresh_tree()
            self.notify("Refreshed")
        elif btn_id == "commit-btn":
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
        import time
        if (time.time() - self._last_tree_refresh) < 0.5:
            return
        try:
            self.query_one("#dir-tree", FilteredDirectoryTree).reload()
            self._last_tree_refresh = time.time()
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
