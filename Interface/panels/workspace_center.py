"""Center workspace — permanent Chat tab + closable file / image tabs."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import TabbedContent, TabPane

from .ai_chat import AIChatPanel
from .code_editor import FileEditorTabPane
from .image_viewer import ImageViewerPanel


CHAT_TAB_ID = "tab-main-chat"


class WorkspaceCenter(Vertical):
    """Tabbed center: first tab is always chat; files open in additional tabs."""

    def __init__(self, models=None, current_model: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._models = models or []
        self._current_model = current_model
        self._path_to_tab: Dict[str, str] = {}
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
