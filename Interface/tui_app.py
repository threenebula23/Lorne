"""TCA IDE — full-screen terminal IDE with 6 panels + drag resize."""
from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import MouseDown, MouseMove, MouseUp
from textual.widgets import Header, Static, Button
from textual.widget import Widget

from .panels.file_explorer import (
    FileExplorerPanel, FileSelected, AddToContext, GitCommitRequested,
    RunFileRequested,
)
from .panels.code_editor import CodeEditorPanel, FileSaved
from .panels.terminal_panel import TerminalPanel
from .panels.version_control import VersionControlPanel, BranchSwitched
from .panels.ai_chat import (
    AIChatPanel, ChatSubmitted, ModelChanged, ModeToggled, StopRequested,
)


class ResizeHandle(Widget):
    """Draggable resize handle placed between panels."""

    DEFAULT_CSS = """
    ResizeHandle {
        width: 1;
        height: 1fr;
        background: #2D2D3D;
        min-width: 1;
        max-width: 1;
    }
    ResizeHandle:hover {
        background: #8B5CF6;
    }
    ResizeHandle.dragging {
        background: #A78BFA;
    }
    ResizeHandle.horizontal {
        width: 1fr;
        height: 1;
        min-height: 1;
        max-height: 1;
        min-width: auto;
        max-width: 100%;
    }
    """

    def __init__(self, target_id: str, direction: str = "left",
                 min_size: int = 14, max_size: int = 60, **kwargs):
        super().__init__(**kwargs)
        self._target_id = target_id
        self._direction = direction
        self._min_size = min_size
        self._max_size = max_size
        self._dragging = False
        self._start_x = 0
        self._start_y = 0
        self._start_size = 0

    def on_mouse_down(self, event: MouseDown) -> None:
        self._dragging = True
        self._start_x = event.screen_x
        self._start_y = event.screen_y
        self.add_class("dragging")
        self.capture_mouse()
        try:
            target = self.app.query_one(f"#{self._target_id}")
            w = target.size.width
            h = target.size.height
            self._start_size = w if self._direction in ("left", "right") else h
        except Exception:
            self._start_size = 30

    def on_mouse_move(self, event: MouseMove) -> None:
        if not self._dragging:
            return
        if self._direction == "left":
            delta = event.screen_x - self._start_x
            new_size = max(self._min_size, min(self._max_size, self._start_size + delta))
        elif self._direction == "right":
            delta = self._start_x - event.screen_x
            new_size = max(self._min_size, min(self._max_size, self._start_size + delta))
        else:
            return
        try:
            target = self.app.query_one(f"#{self._target_id}")
            target.styles.width = new_size
        except Exception:
            pass

    def on_mouse_up(self, event: MouseUp) -> None:
        if self._dragging:
            self._dragging = False
            self.remove_class("dragging")
            self.release_mouse()


class TCAApp(App):
    """TCA full-screen IDE application."""

    CSS_PATH = "tui_app.tcss"
    TITLE = "TCA — Terminal Coding Assistant"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Exit", show=True, priority=True),
        Binding("ctrl+s", "save_file", "Save", show=False),
        Binding("ctrl+f", "toggle_find", "Find", show=False),
        Binding("ctrl+g", "goto_line", "Go to Line", show=False),
        Binding("ctrl+w", "close_tab", "Close Tab", show=False),
        Binding("ctrl+backslash", "focus_terminal", "Terminal", show=False),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=False),
        Binding("ctrl+t", "new_terminal", "New Terminal", show=False),
        Binding("escape", "focus_chat", "Chat", show=False),
        Binding("f5", "run_current_file", "Run File", show=False),
        Binding("ctrl+shift+x", "stop_agent", "Stop Agent", show=False),
        Binding("f6", "resize_left_smaller", "Left -", show=False),
        Binding("f7", "resize_left_larger", "Left +", show=False),
        Binding("f8", "resize_right_smaller", "Right -", show=False),
        Binding("f9", "resize_right_larger", "Right +", show=False),
        Binding("f10", "resize_bottom_toggle", "Toggle Terminal", show=False),
    ]

    def __init__(
        self,
        model_name: str = "",
        branch: str = "",
        models: Optional[List[Dict]] = None,
        on_chat_submit: Optional[Callable[[str], None]] = None,
        on_model_change: Optional[Callable[[str], None]] = None,
        on_mode_toggle: Optional[Callable[[str], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._model_name = model_name
        self._branch = branch
        self._models = models or []
        self._on_chat_submit = on_chat_submit
        self._on_model_change = on_model_change
        self._on_mode_toggle = on_mode_toggle
        self._bridge = None
        self._left_width = 28
        self._right_width = 38
        self._mode_name = "normal"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top-bar"):
            yield Button("✕ Exit", id="app-exit-btn")
            yield Static(f"  {self._model_name}", id="top-model-label")
        with Horizontal(id="main"):
            with Vertical(id="col-left"):
                yield FileExplorerPanel(id="file-explorer")
                yield VersionControlPanel(id="version-control")
            yield ResizeHandle(
                target_id="col-left", direction="left",
                min_size=14, max_size=50, id="resize-left",
            )
            with Vertical(id="col-center"):
                yield CodeEditorPanel(id="code-editor")
                yield TerminalPanel(id="terminal-panel")
            yield ResizeHandle(
                target_id="ai-chat", direction="right",
                min_size=22, max_size=60, id="resize-right",
            )
            yield AIChatPanel(
                models=self._models,
                current_model=self._model_name,
                id="ai-chat",
            )
        status = f" {self._model_name}"
        if self._branch:
            status += f"  ⎇ {self._branch}"
        status += "  │  F10: term  M: menu"
        yield Static(status, id="status-bar")

    # ─── Properties ─────────────────────────────────

    @property
    def file_explorer(self) -> FileExplorerPanel:
        return self.query_one("#file-explorer", FileExplorerPanel)

    @property
    def code_editor(self) -> CodeEditorPanel:
        return self.query_one("#code-editor", CodeEditorPanel)

    @property
    def terminal(self) -> TerminalPanel:
        return self.query_one("#terminal-panel", TerminalPanel)

    @property
    def version_control(self) -> VersionControlPanel:
        return self.query_one("#version-control", VersionControlPanel)

    @property
    def chat(self) -> AIChatPanel:
        return self.query_one("#ai-chat", AIChatPanel)

    @property
    def status_bar(self) -> Static:
        return self.query_one("#status-bar", Static)

    # ─── Message handlers ──────────────────────────

    @on(FileSelected)
    def on_file_open(self, event: FileSelected) -> None:
        self.code_editor.open_file(event.path)

    @on(AddToContext)
    def on_add_to_context(self, event: AddToContext) -> None:
        try:
            self.chat.register_context_hint(event.path)
            self.notify(f"Контекст: {event.path.name} (агент не запущен)")
        except Exception as e:
            self.chat.add_error(f"Cannot add context: {e}")

    @on(GitCommitRequested)
    def on_git_commit(self, event: GitCommitRequested) -> None:
        try:
            from Agent.git_integration import get_git_manager
            gm = get_git_manager()
            if gm.available:
                result = gm.auto_snapshot(event.message, event.files or None)
                if result:
                    self.chat.add_success(f"Committed: {result[:8]}")
                else:
                    self.chat.add_warning("Nothing to commit")
            else:
                self.chat.add_error("Git not available")
        except Exception as e:
            self.chat.add_error(f"Commit error: {e}")

    @on(RunFileRequested)
    def on_run_file(self, event: RunFileRequested) -> None:
        p = event.path
        if p.suffix == ".py":
            cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(p))}"
        elif p.suffix == ".sh":
            cmd = f"bash {shlex.quote(str(p))}"
        elif p.suffix in (".js", ".ts"):
            cmd = f"node {shlex.quote(str(p))}"
        else:
            cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(p))}"
        self.terminal.run_command(cmd)
        self.chat.add_info(f"Running: {cmd}")

    @on(FileSaved)
    def on_file_saved(self, event: FileSaved) -> None:
        self.file_explorer.refresh_tree()

    @on(BranchSwitched)
    def on_branch_switched(self, event: BranchSwitched) -> None:
        self._branch = event.branch
        self._update_status()

    @on(ChatSubmitted)
    def on_chat_message(self, event: ChatSubmitted) -> None:
        text = event.text
        self.chat.add_user_message(text)
        if self._on_chat_submit:
            hints = self.chat.get_context_hints()
            if hints:
                text = (
                    "[Pinned paths — check these files if relevant]\n"
                    + "\n".join(hints)
                    + "\n\n---\n"
                    + text
                )
            self._on_chat_submit(text)

    @on(ModelChanged)
    def on_model_changed(self, event: ModelChanged) -> None:
        self._model_name = event.model_id
        self._update_status()
        try:
            self.query_one("#top-model-label", Static).update(f"  {event.model_id}")
        except Exception:
            pass
        if self._on_model_change:
            self._on_model_change(event.model_id)

    @on(ModeToggled)
    def on_mode_toggled(self, event: ModeToggled) -> None:
        self._mode_name = str(event.mode or "normal")
        self._update_status()
        if self._on_mode_toggle:
            self._on_mode_toggle(event.mode)

    @on(StopRequested)
    def on_stop_requested(self, event: StopRequested) -> None:
        if self._bridge:
            self._bridge.request_stop()
            self.chat.add_warning("Stop requested — agent will halt after current operation")

    @on(Button.Pressed, "#app-exit-btn")
    def on_exit_click(self) -> None:
        self.exit()

    # ─── Actions ────────────────────────────────────

    def action_focus_chat(self) -> None:
        try:
            self.query_one("#chat-input").focus()
        except Exception:
            pass

    def action_focus_terminal(self) -> None:
        try:
            self.terminal.focus()
        except Exception:
            pass

    def action_toggle_sidebar(self) -> None:
        try:
            col = self.query_one("#col-left", Vertical)
            col.display = not col.display
        except Exception:
            pass

    def action_save_file(self) -> None:
        self.code_editor.action_save_file()

    def action_toggle_find(self) -> None:
        self.code_editor.action_toggle_find()

    def action_goto_line(self) -> None:
        self.code_editor.action_goto_line()

    def action_close_tab(self) -> None:
        self.code_editor.action_close_tab()

    def action_new_terminal(self) -> None:
        self.terminal._add_terminal_tab()

    def action_run_current_file(self) -> None:
        info = self.code_editor._get_active_file_info()
        if info and info.get("path"):
            p = info["path"]
            if p.suffix == ".py":
                cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(p))}"
                self.terminal.run_command(cmd)
                self.chat.add_info(f"Running: {cmd}")

    def action_stop_agent(self) -> None:
        if self._bridge:
            self._bridge.request_stop()
            self.chat.add_warning("Stop requested")

    def _set_width(self, widget_id: str, width: int) -> None:
        try:
            widget = self.query_one(widget_id)
            widget.styles.width = width
        except Exception:
            pass

    def action_resize_left_smaller(self) -> None:
        self._left_width = max(14, self._left_width - 4)
        self._set_width("#col-left", self._left_width)

    def action_resize_left_larger(self) -> None:
        self._left_width = min(50, self._left_width + 4)
        self._set_width("#col-left", self._left_width)

    def action_resize_right_smaller(self) -> None:
        self._right_width = max(22, self._right_width - 4)
        self._set_width("#ai-chat", self._right_width)

    def action_resize_right_larger(self) -> None:
        self._right_width = min(60, self._right_width + 4)
        self._set_width("#ai-chat", self._right_width)

    def action_resize_bottom_toggle(self) -> None:
        try:
            term = self.query_one("#terminal-panel", TerminalPanel)
            term.display = not term.display
        except Exception:
            pass

    # ─── Public API ─────────────────────────────────

    def set_bridge(self, bridge) -> None:
        self._bridge = bridge

    def update_status(self, model: str = "", branch: str = "",
                      tokens: str = "", rag: str = "") -> None:
        parts = []
        if model:
            parts.append(f" {model}")
            self._model_name = model
        if branch:
            parts.append(f"⎇ {branch}")
            self._branch = branch
        if tokens:
            parts.append(f"{tokens}")
        if rag:
            parts.append(f"RAG: {rag}")
        parts.append(f"MODE: {self._mode_name.upper()}")
        parts.append("F10: term  M: menu")
        self.status_bar.update(" │ ".join(parts) if parts else "")

    def _update_status(self) -> None:
        self.update_status(model=self._model_name, branch=self._branch)
