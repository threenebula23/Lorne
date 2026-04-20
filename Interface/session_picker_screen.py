"""Модальный экран: выбрать существующий чат, новый или удалить."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from Interface.modal_style import MODAL_SHARED_CSS, apply_accent_to


def _fmt_ts(iso: str) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:19]


class SessionPickerScreen(ModalScreen[Optional[Dict[str, Any]]]):
    """Возвращает {action: 'new'} | {action: 'open', session_id: str} | None (выход)."""

    DEFAULT_CSS = MODAL_SHARED_CSS + """
    SessionPickerScreen { align: center middle; }
    #sp-root {
        width: 92%;
        height: 86%;
        max-width: 108;
    }
    #sp-title {
        height: auto;
    }
    #sp-subtitle {
        color: #9CA3AF;
        margin: 0 0 1 0;
    }
    #sp-scroll {
        height: 1fr;
        border: solid #2D2D3D;
        background: #12121A;
        padding: 0 1;
    }
    .sp-row {
        height: auto;
        min-height: 4;
        layout: horizontal;
        padding: 1 1;
        margin: 0 0 1 0;
        background: #1a1528;
        border: tall #2D2D3D;
    }
    .sp-row:focus-within { background: #252036; }
    .sp-meta {
        width: 1fr;
        min-height: 3;
        content-align: left middle;
        color: #E5E7EB;
    }
    .sp-actions {
        width: auto;
        height: auto;
        layout: horizontal;
        content-align: right middle;
    }
    .sp-actions Button {
        min-width: 12;
        margin: 0 0 0 1;
        height: 3;
    }
    """

    def __init__(self, sessions: List[Dict[str, Any]]) -> None:
        super().__init__()
        self._sessions = list(sessions or [])

    def compose(self) -> ComposeResult:
        with Vertical(id="sp-root", classes="modal-card"):
            yield Label("Выберите чат или создайте новый", id="sp-title", classes="modal-title")
            yield Label(
                "Совет: новый чат создаёт чистую сессию; удалённые записи можно восстановить только из git-истории.",
                id="sp-subtitle",
            )
            with VerticalScroll(id="sp-scroll"):
                if not self._sessions:
                    yield Static(
                        "Нет сохранённых сессий — создайте новый чат кнопкой ниже.",
                        classes="sp-meta",
                    )
                for s in self._sessions:
                    sid = str(s.get("session_id", ""))
                    title = (s.get("title") or sid)[:80]
                    upd = _fmt_ts(str(s.get("updated_at", "")))
                    mc = int(s.get("message_count") or 0)
                    meta = f"{title}\n[dim]обновл. {upd}  ·  сообщ. ~{mc}[/dim]"
                    with Horizontal(classes="sp-row"):
                        yield Static(meta, classes="sp-meta", markup=True)
                        with Horizontal(classes="sp-actions"):
                            yield Button("Открыть", id=f"sp-open-{sid}", variant="primary")
                            yield Button("Удалить", id=f"sp-del-{sid}", variant="error")
            with Horizontal(id="sp-bottom", classes="modal-footer"):
                yield Button("Новый чат", id="sp-new", variant="success")
                yield Button("Выход из TCA", id="sp-quit", variant="default")

    def on_mount(self) -> None:
        apply_accent_to(
            self,
            container_id="sp-root",
            title_id="sp-title",
            title_text="Выберите чат или создайте новый",
        )

    @on(Button.Pressed, "#sp-new")
    def on_new(self) -> None:
        self.dismiss({"action": "new"})

    @on(Button.Pressed, "#sp-quit")
    def on_quit(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed)
    def on_row_btn(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("sp-open-"):
            sid = bid[len("sp-open-") :]
            if sid:
                self.dismiss({"action": "open", "session_id": sid})
        elif bid.startswith("sp-del-"):
            sid = bid[len("sp-del-") :]
            if sid:
                self.dismiss({"action": "delete", "session_id": sid})
