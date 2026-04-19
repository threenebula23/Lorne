"""Center workspace — permanent Chat tab + closable file / image tabs."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static, TabbedContent, TabPane

from .ai_chat import AIChatPanel
from .code_editor import CloseWorkspaceTab, FileEditorTabPane
from .image_viewer import ImageViewerPanel


CHAT_TAB_ID = "tab-main-chat"

_SETTINGS_SECTION_TITLES = {
    "personalization": "⚙ Персонализация",
    "agents": "⚙ Агенты",
    "openrouter": "⚙ OpenRouter",
    "ollama": "⚙ Ollama",
}


class SettingsWorkspacePane(Vertical):
    """Settings body for a workspace tab: top bar (title + close) + scroll mount."""

    DEFAULT_CSS = """
    SettingsWorkspacePane {
        height: 1fr;
    }
    #settings-ws-toolbar {
        dock: top;
        height: auto;
        min-height: 3;
        layout: horizontal;
        background: #151520;
        padding: 0 0 1 0;
    }
    #settings-ws-toolbar Button {
        min-width: 18;
        height: 3;
        margin: 0 0 0 1;
    }
    #settings-ws-toolbar Static {
        content-align: left middle;
        width: 1fr;
    }
    """

    def __init__(self, section: str, close_tab_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._section = section.strip().lower()
        self._close_tab_id = close_tab_id
        safe = close_tab_id.replace("-", "_")
        self._scroll_id = f"wsscroll-{safe}"
        self._close_btn_id = f"settings-ws-close-{safe}"

    def compose(self) -> ComposeResult:
        title = _SETTINGS_SECTION_TITLES.get(
            self._section, f"⚙ {self._section.capitalize()}",
        )
        with Horizontal(id="settings-ws-toolbar"):
            yield Static(title)
            yield Button("Закрыть вкладку", id=self._close_btn_id, variant="error")
        yield VerticalScroll(id=self._scroll_id)

    def on_mount(self) -> None:
        try:
            chat = self.app.query_one("#ai-chat", AIChatPanel)
            scroll = self.query_one(f"#{self._scroll_id}", VerticalScroll)
            chat.render_settings_into(scroll, self._section)
        except Exception:
            pass

    @on(Button.Pressed)
    def _on_toolbar_button(self, event: Button.Pressed) -> None:
        if event.button.id == self._close_btn_id:
            self.post_message(CloseWorkspaceTab(self._close_tab_id))


class WorkspaceCenter(Vertical):
    """Tabbed center: first tab is always chat; files open in additional tabs."""

    def __init__(self, models=None, current_model: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._models = models or []
        self._current_model = current_model
        self._path_to_tab: Dict[str, str] = {}
        self._settings_section_to_tab: Dict[str, str] = {}
        self._tab_counter = 0

    def compose(self) -> ComposeResult:
        with TabbedContent(initial=CHAT_TAB_ID):
            with TabPane("💬 Чат", id=CHAT_TAB_ID):
                yield AIChatPanel(
                    models=self._models,
                    current_model=self._current_model,
                    id="ai-chat",
                )

    def _tabs(self) -> TabbedContent:
        return self.query_one(TabbedContent)

    @property
    def chat(self) -> AIChatPanel:
        return self.query_one("#ai-chat", AIChatPanel)

    def focus_chat_tab(self) -> None:
        try:
            self._tabs().active = CHAT_TAB_ID
        except Exception:
            pass

    def open_settings_tab(self, section: str) -> None:
        sec = (section or "").strip().lower()
        if sec not in {"personalization", "agents", "openrouter", "ollama"}:
            sec = "personalization"
        existing = self._settings_section_to_tab.get(sec)
        if existing:
            try:
                self._tabs().active = existing
            except Exception:
                pass
            return

        self._tab_counter += 1
        tab_id = f"ws-settings-{self._tab_counter}"
        self._settings_section_to_tab[sec] = tab_id

        title = _SETTINGS_SECTION_TITLES.get(sec, f"⚙ {sec.capitalize()}")
        body = SettingsWorkspacePane(sec, tab_id)
        pane = TabPane(title, body, id=tab_id)
        self._tabs().add_pane(pane)
        try:
            self._tabs().active = tab_id
        except Exception:
            pass

    def close_active_settings_tab(self) -> bool:
        """Close the active tab if it is a settings tab. Returns True if closed."""
        tabs = self._tabs()
        aid = tabs.active
        if not aid or not str(aid).startswith("ws-settings-"):
            return False
        self.close_tab_by_id(aid)
        try:
            tabs.active = CHAT_TAB_ID
        except Exception:
            pass
        return True

    def open_path(self, path: Path) -> None:
        p = path.resolve()
        key = str(p)
        if key in self._path_to_tab:
            try:
                self._tabs().active = self._path_to_tab[key]
            except Exception:
                pass
            return

        self._tab_counter += 1
        tab_id = f"ws-file-{self._tab_counter}"
        self._path_to_tab[key] = tab_id

        suf = p.suffix.lower()
        if suf in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp", ".ico"):
            viewer = ImageViewerPanel()
            pane = TabPane(p.name, viewer, id=tab_id)
            self._tabs().add_pane(pane)
            viewer.show_image(p)
        else:
            editor = FileEditorTabPane(p, close_tab_id=tab_id)
            pane = TabPane(p.name, editor, id=tab_id)
            self._tabs().add_pane(pane)

        try:
            self._tabs().active = tab_id
        except Exception:
            pass

    def close_tab_by_id(self, tab_id: str) -> None:
        if tab_id == CHAT_TAB_ID:
            return
        tabs = self._tabs()
        for k, v in list(self._path_to_tab.items()):
            if v == tab_id:
                self._path_to_tab.pop(k, None)
        for sec, tid in list(self._settings_section_to_tab.items()):
            if tid == tab_id:
                self._settings_section_to_tab.pop(sec, None)
        try:
            tabs.remove_pane(tab_id)
        except Exception:
            pass

    def close_path(self, path: Path) -> None:
        key = str(path.resolve())
        tab_id = self._path_to_tab.get(key)
        if tab_id:
            self.close_tab_by_id(tab_id)

    def close_active_if_not_chat(self) -> bool:
        """Returns True if a non-chat tab was closed."""
        tabs = self._tabs()
        aid = tabs.active
        if not aid or aid == CHAT_TAB_ID:
            return False
        self.close_tab_by_id(aid)
        try:
            tabs.active = CHAT_TAB_ID
        except Exception:
            pass
        return True
