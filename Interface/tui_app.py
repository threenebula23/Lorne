"""TCA IDE — чат-центричный TUI: файлы слева сверху, агенты слева снизу, вкладки по центру."""
from __future__ import annotations

import shlex
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Static, Button, TextArea

from Interface.ui_prefs import load_prefs
from Interface.themes import apply_theme

from .panels.file_explorer import (
    FileExplorerPanel, FileSelected, AddToContext, RunFileRequested,
)
from .panels.code_editor import FileEditorTabPane, FileSaved, CloseWorkspaceTab
from .panels.workspace_center import WorkspaceCenter, CHAT_TAB_ID
from .panels.active_agents_panel import (
    ActiveAgentsPanel, AgentWorkerSelected, AgentMainChatSelected,
)
from .panels.ai_chat import (
    AIChatPanel, ChatSubmitted, ModelChanged, ModeToggled, StopRequested,
)


class TCAApp(App):
    """TCA full-screen IDE application."""

    CSS_PATH = "tui_app.tcss"
    TITLE = "TCA — Terminal Coding Assistant"
    LAYERS = ["base", "overlay"]

    BINDINGS = [
        Binding("ctrl+q", "quit", "Exit", show=True, priority=True),
        Binding("ctrl+s", "save_file", "Save", show=False),
        Binding("ctrl+f", "toggle_find", "Find", show=False),
        Binding("ctrl+g", "goto_line", "Go to Line", show=False),
        Binding("ctrl+w", "close_tab", "Close Tab", show=False),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=False),
        Binding("escape", "focus_chat", "Chat", show=False),
        Binding("f5", "run_current_file", "Run File", show=False),
        Binding("ctrl+shift+x", "stop_agent", "Stop Agent", show=False),
        Binding("f6", "resize_left_smaller", "Left -", show=False),
        Binding("f7", "resize_left_larger", "Left +", show=False),
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
        self._mode_name = "normal"

    def on_mount(self) -> None:
        prefs = load_prefs()
        try:
            apply_theme(self, str(prefs.get("theme", "Purple Dark")))
        except Exception:
            pass
        dens = str(prefs.get("density", "normal"))
        if dens not in ("compact", "normal", "spacious"):
            dens = "normal"
        for d in ("compact", "normal", "spacious"):
            self.remove_class(f"density-{d}")
        self.add_class(f"density-{dens}")

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top-bar"):
            yield Button("✕ Exit", id="app-exit-btn")
        with Horizontal(id="main"):
            with Vertical(id="col-left"):
                yield FileExplorerPanel(id="file-explorer")
                yield ActiveAgentsPanel(id="active-agents")
            yield WorkspaceCenter(
                models=self._models,
                current_model=self._model_name,
                id="workspace-center",
            )
        status = f" {self._model_name}"
        if self._branch:
            status += f"  ⎇ {self._branch}"
        status += "  │  Esc: чат  M: меню"
        yield Static(status, id="status-bar")

    @property
    def file_explorer(self) -> FileExplorerPanel:
        return self.query_one("#file-explorer", FileExplorerPanel)

    @property
    def workspace(self) -> WorkspaceCenter:
        return self.query_one("#workspace-center", WorkspaceCenter)

    @property
    def chat(self) -> AIChatPanel:
        return self.workspace.chat

    @property
    def active_agents(self) -> ActiveAgentsPanel:
        return self.query_one("#active-agents", ActiveAgentsPanel)

    @property
    def status_bar(self) -> Static:
        return self.query_one("#status-bar", Static)

    @on(FileSelected)
    def on_file_open(self, event: FileSelected) -> None:
        self.workspace.open_path(event.path)

    @on(AddToContext)
    def on_add_to_context(self, event: AddToContext) -> None:
        try:
            self.chat.register_context_hint(event.path)
            self.notify(f"Контекст: {event.path.name}")
        except Exception as e:
            self.chat.add_error(f"Контекст: {e}")

    @on(RunFileRequested)
    def on_run_file(self, event: RunFileRequested) -> None:
        p = event.path
        if p.suffix == ".py":
            cmd = [sys.executable, str(p)]
        elif p.suffix == ".sh":
            cmd = ["bash", str(p)]
        elif p.suffix in (".js", ".ts"):
            cmd = ["node", str(p)]
        else:
            cmd = [sys.executable, str(p)]

        def _run() -> None:
            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=180, cwd=str(Path.cwd()),
                )
                lines = []
                if r.stdout:
                    lines.append(r.stdout[:4000])
                if r.stderr:
                    lines.append("stderr:\n" + r.stderr[:2000])
                if r.returncode != 0:
                    lines.append(f"(код выхода {r.returncode})")
                msg = "\n".join(lines) if lines else "(нет вывода)"
                if self._bridge:
                    self._bridge.on_info(f"▶ {' '.join(shlex.quote(x) for x in cmd)}\n{msg}")
            except Exception as e:
                if self._bridge:
                    self._bridge.on_error(f"Run: {e}")

        self.chat.add_info(f"Запуск: {' '.join(shlex.quote(x) for x in cmd)}")
        threading.Thread(target=_run, daemon=True).start()

    @on(FileSaved)
    def on_file_saved(self, event: FileSaved) -> None:
        self.file_explorer.refresh_tree()

    @on(ChatSubmitted)
    def on_chat_message(self, event: ChatSubmitted) -> None:
        text = event.text
        paths = list(event.image_paths or [])
        if paths:
            block = "\n".join(f"[Image file: {p}]" for p in paths)
            text = block + "\n\n" + text
        self.chat.add_user_message(event.text)
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
            self.chat.add_warning("Остановка — агент завершит текущую операцию")

    @on(Button.Pressed, "#app-exit-btn")
    def on_exit_click(self) -> None:
        self.exit()

    @on(AgentWorkerSelected)
    def on_agent_worker_selected(self, event: AgentWorkerSelected) -> None:
        self.workspace.focus_chat_tab()
        self.chat.set_view_worker(event.worker_id)

    @on(AgentMainChatSelected)
    def on_agent_main_chat(self) -> None:
        self.workspace.focus_chat_tab()
        self.chat.set_view_worker(None)

    @on(CloseWorkspaceTab)
    def on_close_workspace_tab(self, event: CloseWorkspaceTab) -> None:
        self.workspace.close_tab_by_id(event.tab_id)

    def action_focus_chat(self) -> None:
        try:
            self.workspace.focus_chat_tab()
            self.query_one("#chat-input", TextArea).focus()
        except Exception:
            pass

    def action_toggle_sidebar(self) -> None:
        try:
            col = self.query_one("#col-left", Vertical)
            col.display = not col.display
        except Exception:
            pass

    def action_save_file(self) -> None:
        try:
            tabs = self.workspace._tabs()
            aid = tabs.active
            if not aid or aid == CHAT_TAB_ID:
                return
            pane = tabs.get_pane(aid)
            editor = pane.query_one(FileEditorTabPane)
            editor._save_to_disk()
        except Exception:
            pass

    def action_toggle_find(self) -> None:
        self.notify("Поиск: откройте файл во вкладке и используйте Ctrl+F в редакторе")

    def action_goto_line(self) -> None:
        self.notify("Переход к строке из вкладки файла")

    def action_close_tab(self) -> None:
        self.workspace.close_active_if_not_chat()

    def action_run_current_file(self) -> None:
        try:
            tabs = self.workspace._tabs()
            aid = tabs.active
            if not aid or aid == CHAT_TAB_ID:
                self.notify("Откройте файл во вкладке", severity="warning")
                return
            pane = tabs.get_pane(aid)
            ed = pane.query_one(FileEditorTabPane)
            self.post_message(RunFileRequested(ed._path))
        except Exception:
            self.notify("Нет активного файла", severity="warning")

    def action_stop_agent(self) -> None:
        if self._bridge:
            self._bridge.request_stop()
            self.chat.add_warning("Остановка запрошена")

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
        parts.append("Esc: чат  M: меню")
        self.status_bar.update(" │ ".join(parts) if parts else "")

    def _update_status(self) -> None:
        self.update_status(model=self._model_name, branch=self._branch)
