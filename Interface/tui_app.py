"""TCA IDE — чат-центричный TUI: файлы слева сверху, агенты слева снизу, вкладки по центру."""
from __future__ import annotations

import shlex
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from textual import on
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Static, Button, TextArea, Select, Checkbox

from Interface.ui_prefs import load_prefs
from Interface.themes import apply_theme

from .panels.file_explorer import (
    FileExplorerPanel, FileSelected, AddToContext, RunFileRequested, OpenChatSettings,
)
from .panels.code_editor import FileEditorTabPane, FileSaved, CloseWorkspaceTab
from .panels.workspace_center import WorkspaceCenter, CHAT_TAB_ID
from .panels.active_agents_panel import (
    ActiveAgentsPanel, AgentWorkerSelected, AgentMainChatSelected,
)
from .panels.ai_chat import (
    AIChatPanel, ChatSubmitted, ModelChanged, ModeToggled, StopRequested,
    RollbackRequested, DeepCheckpointAction,
)
from .session_picker_screen import SessionPickerScreen


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
        on_chat_submit: Optional[Callable[..., None]] = None,
        on_model_change: Optional[Callable[[str], None]] = None,
        on_mode_toggle: Optional[Callable[[str], None]] = None,
        on_session_resolved: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_chat_rollback: Optional[Callable[[int], None]] = None,
        on_app_close: Optional[Callable[[], None]] = None,
        on_deep_checkpoint: Optional[Callable[[str, str], None]] = None,
        require_session_picker: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._model_name = model_name
        self._branch = branch
        self._models = models or []
        self._on_chat_submit = on_chat_submit
        self._on_model_change = on_model_change
        self._on_mode_toggle = on_mode_toggle
        self._on_session_resolved = on_session_resolved
        self._on_chat_rollback = on_chat_rollback
        self._on_app_close = on_app_close
        self._on_deep_checkpoint = on_deep_checkpoint
        self._require_session_picker = require_session_picker
        self._bridge = None
        self._left_width = 28
        self._mode_name = "normal"
        self._shutdown_done = False

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
        if self._require_session_picker and self._on_session_resolved:
            self.set_timer(0.05, self._push_session_picker)

    def _push_session_picker(self) -> None:
        try:
            from Agent.checkpoint import list_sessions

            rows = list_sessions(limit=80)
        except Exception:
            rows = []
        self.push_screen(SessionPickerScreen(rows), self._on_session_picker_result)

    def _on_session_picker_result(self, result: Optional[Dict[str, Any]]) -> None:
        if result is None:
            self._run_shutdown_hooks()
            self.exit()
            return
        act = str(result.get("action", ""))
        if act == "delete":
            try:
                from Agent.checkpoint import delete_session, list_sessions

                sid = str(result.get("session_id", ""))
                if sid:
                    delete_session(sid)
            except Exception:
                pass
            self._push_session_picker()
            return
        if self._on_session_resolved:
            self._on_session_resolved(result)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top-bar"):
            yield Button("✕ Exit", id="app-exit-btn")
            yield Button("💬 Chat", id="app-chat-btn", variant="primary")
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

    @on(OpenChatSettings)
    def on_open_chat_settings(self, event: OpenChatSettings) -> None:
        try:
            sec = (event.section or "").strip().lower()
            if sec in {"close", "closed", "off", "none"}:
                self.workspace.close_active_settings_tab()
                return
            self.workspace.focus_chat_tab()
            self.workspace.open_settings_tab(sec)
        except Exception as e:
            self.chat.add_error(f"Settings open: {e}")

    # Settings widgets live in workspace tabs (not under #ai-chat); bind on App.
    @on(Button.Pressed, "#sp-apply-accent")
    def _app_on_apply_accent(self) -> None:
        self.chat.on_apply_accent()

    @on(Button.Pressed, "#sp-open-palette")
    def _app_on_open_palette(self) -> None:
        self.chat.on_open_palette()

    @on(Select.Changed, "#sp-theme")
    def _app_on_sp_theme(self, event: Select.Changed) -> None:
        self.chat.on_sp_theme(event)

    @on(Select.Changed, "#sp-density")
    def _app_on_sp_density(self, event: Select.Changed) -> None:
        self.chat.on_sp_density(event)

    @on(Select.Changed, "#sp-syntax")
    def _app_on_sp_syntax(self, event: Select.Changed) -> None:
        self.chat.on_sp_syntax(event)

    @on(Select.Changed, "#sa-profile")
    def _app_on_sa_profile(self, event: Select.Changed) -> None:
        self.chat.on_sa_profile(event)

    @on(Checkbox.Changed, "#sa-browser")
    def _app_on_sa_browser(self, event: Checkbox.Changed) -> None:
        self.chat.on_sa_browser(event)

    @on(Checkbox.Changed, "#sa-playwright")
    def _app_on_sa_playwright(self, event: Checkbox.Changed) -> None:
        self.chat.on_sa_playwright(event)

    @on(Checkbox.Changed, "#sa-custom-tools")
    def _app_on_sa_custom_tools(self, event: Checkbox.Changed) -> None:
        self.chat.on_sa_custom_tools(event)

    @on(Checkbox.Changed, "#sa-research-deep-fetch")
    def _app_on_sa_research_deep_fetch(self, event: Checkbox.Changed) -> None:
        self.chat.on_sa_research_deep_fetch(event)

    @on(Select.Changed, "#sa-orch-mode")
    def _app_on_sa_orch_mode(self, event: Select.Changed) -> None:
        self.chat.on_sa_orch_mode(event)

    @on(Button.Pressed, "#sa-apply")
    def _app_on_sa_apply(self) -> None:
        self.chat.on_sa_apply()

    @on(Button.Pressed, "#sor-save-key")
    def _app_on_sor_save_key(self) -> None:
        self.chat.on_sor_save_key()

    @on(Button.Pressed, "#sor-check-balance")
    def _app_on_sor_check_balance(self) -> None:
        self.chat.on_sor_check_balance()

    @on(Button.Pressed, "#sor-add-model")
    def _app_on_sor_add_model(self) -> None:
        self.chat.on_sor_add_model()

    @on(Button.Pressed, "#sol-save-conn")
    def _app_on_sol_save_conn(self) -> None:
        self.chat.on_sol_save_conn()

    @on(Select.Changed, "#sol-preset-select")
    def _app_on_sol_preset_changed(self, event: Select.Changed) -> None:
        self.chat.on_sol_preset_changed(event)

    @on(Button.Pressed, "#sol-save-preset")
    def _app_on_sol_save_preset(self) -> None:
        self.chat.on_sol_save_preset()

    @on(Button.Pressed, "#sol-apply-model-settings")
    def _app_on_sol_apply_model_settings(self) -> None:
        self.chat.on_sol_apply_model_settings()

    @on(Button.Pressed, "#sol-refresh")
    def _app_on_sol_refresh(self) -> None:
        self.chat.on_sol_refresh()

    @on(Select.Changed, "#sol-model-select")
    def _app_on_sol_model_select(self, event: Select.Changed) -> None:
        self.chat.on_sol_model_select(event)

    @on(Button.Pressed, "#sol-add")
    def _app_on_sol_add(self) -> None:
        self.chat.on_sol_add()

    @on(FileSaved)
    def on_file_saved(self, event: FileSaved) -> None:
        self.file_explorer.refresh_tree()

    @on(RollbackRequested)
    def on_rollback_requested(self, event: RollbackRequested) -> None:
        if self._on_chat_rollback:
            self._on_chat_rollback(event.turn_index)

    @on(DeepCheckpointAction)
    def on_deep_checkpoint_action(self, event: DeepCheckpointAction) -> None:
        """Forward a Deep Solver checkpoint button click to the agent side.

        The agent owns the ``apply_checkpoint_action`` handler because it
        needs live references to ``messages`` and the enhanced system
        prompt; the TUI just relays the intent. On 'continue' the agent
        also mounts a context chip via the bridge.
        """
        handler = getattr(self, "_on_deep_checkpoint", None)
        if handler:
            try:
                handler(event.cp_id, event.action)
            except Exception:
                pass

    @on(ChatSubmitted)
    def on_chat_message(self, event: ChatSubmitted) -> None:
        text = event.text
        bubble = getattr(event, "bubble_text", None) or event.text
        paths = list(event.image_paths or [])
        if paths:
            block = "\n".join(f"[Image file: {p}]" for p in paths)
            text = block + "\n\n" + text
        if self._on_chat_submit:
            hints = self.chat.get_context_hints()
            if hints:
                text = (
                    "[Pinned paths — check these files if relevant]\n"
                    + "\n".join(hints)
                    + "\n\n---\n"
                    + text
                )
            try:
                self._on_chat_submit(text, bubble)
            except TypeError:
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
        self._run_shutdown_hooks()
        self.exit()

    @on(Button.Pressed, "#app-chat-btn")
    def on_chat_picker_click(self) -> None:
        """Open the existing session picker screen (same one used at startup)."""
        try:
            from Agent.checkpoint import list_sessions

            rows = list_sessions(limit=80)
        except Exception:
            rows = []
        self.push_screen(SessionPickerScreen(rows), self._on_session_picker_result)

    def action_quit(self) -> None:
        self._run_shutdown_hooks()
        self.exit()

    def _run_shutdown_hooks(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        if self._on_app_close:
            try:
                self._on_app_close()
            except Exception:
                pass

    def on_shutdown(self, event: events.Shutdown) -> None:
        self._run_shutdown_hooks()

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
