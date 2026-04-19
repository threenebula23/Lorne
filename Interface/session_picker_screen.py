"""Модальный экран: выбрать существующий чат, новый или удалить."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


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

    DEFAULT_CSS = """
    SessionPickerScreen { align: center middle; }
    #sp-root {
        width: 92%;
        height: 88%;
        max-width: 96;
        background: #151520;
        border: round #8B5CF6;
        padding: 1 2;
    }
    #sp-title { height: 1; text-style: bold; margin: 0 0 1 0; color: #A78BFA; }
    #sp-scroll { height: 1fr; border: solid #2D2D3D; }
    .sp-row {
        height: auto;
        min-height: 4;
        layout: horizontal;
        padding: 0 1;
        margin: 0 0 1 0;
        background: #1a1528;
    }
    .sp-row:focus-within {
        background: #252036;
    }
    .sp-meta { width: 1fr; min-height: 3; content-align: left middle; }
    .sp-actions { width: auto; height: auto; layout: horizontal; }
    .sp-actions Button { min-width: 10; margin: 0 0 0 1; }
    #sp-bottom { height: auto; margin-top: 1; layout: horizontal; }
    #sp-bottom Button { min-width: 22; margin: 0 1 0 0; }
    """

    def __init__(self, sessions: List[Dict[str, Any]]) -> None:
        super().__init__()
        self._sessions = list(sessions or [])

    def compose(self) -> ComposeResult:
        with Vertical(id="sp-root"):
            yield Label("Выберите чат или создайте новый", id="sp-title")
            with VerticalScroll(id="sp-scroll"):
                for s in self._sessions:
                    sid = str(s.get("session_id", ""))
                    title = (s.get("title") or sid)[:80]
                    upd = _fmt_ts(str(s.get("updated_at", "")))
                    mc = int(s.get("message_count") or 0)
                    meta = f"{title}\nобновл. {upd}  ·  сообщ. ~{mc}"
                    with Horizontal(classes="sp-row"):
                        yield Static(meta, classes="sp-meta")
                        with Horizontal(classes="sp-actions"):
                            yield Button("Открыть", id=f"sp-open-{sid}", variant="primary")
                            yield Button("Удалить", id=f"sp-del-{sid}", variant="error")
            with Horizontal(id="sp-bottom"):
                yield Button("Новый чат", id="sp-new", variant="success")
                yield Button("Выход из TCA", id="sp-quit", variant="default")

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
