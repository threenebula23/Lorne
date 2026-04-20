"""In-chat card representing an auto-checkpoint made by the Deep Solver.

The Deep Solver drops a checkpoint every few steps so the user can safely
rewind (``Откат``) or seed a follow-up prompt from a specific point
(``Продолжить``). This widget is deliberately read-only aside from those
two buttons; all state (which turn the checkpoint maps to, title, brief
summary) comes from the parent panel when it's mounted.

Button IDs follow a strict schema:
    deepcp-rollback-<cp_id>
    deepcp-continue-<cp_id>
The parent ``AIChatPanel`` listens for those via ``on(Button.Pressed)``
and forwards the intent through the TUI bridge into
``Agent.deep_solver`` where the actual rollback / continue logic runs.
"""
from __future__ import annotations

from typing import Optional

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static


def _accent_color() -> str:
    try:
        from Interface.ui_prefs import load_prefs
        from Interface.themes import get_theme
        prefs = load_prefs()
        theme = get_theme(str(prefs.get("theme", "Purple Dark")))
        return str(prefs.get("accent_color") or theme.get("accent") or "#8B5CF6")
    except Exception:
        return "#8B5CF6"


class DeepCheckpointBlock(Vertical):
    """Compact card with Откат / Продолжить buttons for a Deep checkpoint."""

    DEFAULT_CSS = """
    DeepCheckpointBlock {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: #12121A;
        border: round #2D2D3D;
    }
    DeepCheckpointBlock .deepcp-title {
        height: auto;
        text-style: bold;
    }
    DeepCheckpointBlock .deepcp-summary {
        height: auto;
        color: #9CA3AF;
        margin: 0 0 1 0;
    }
    DeepCheckpointBlock .deepcp-buttons {
        height: auto;
        layout: horizontal;
        margin: 1 0 0 0;
    }
    DeepCheckpointBlock .deepcp-buttons Button {
        margin: 0 2 0 0;
        min-width: 22;
        height: 3;
        border: round #2D2D3D;
        padding: 0 2;
        text-style: bold;
    }
    DeepCheckpointBlock .deepcp-rollback {
        background: #2A1A1A;
        color: #FCA5A5;
    }
    DeepCheckpointBlock .deepcp-rollback:hover {
        background: #3F1F1F;
    }
    DeepCheckpointBlock .deepcp-continue {
        background: #1C2A1C;
        color: #A7F3D0;
    }
    DeepCheckpointBlock .deepcp-continue:hover {
        background: #25402B;
    }
    """

    def __init__(
        self,
        checkpoint_id: str,
        index: int,
        title: str,
        summary: str = "",
        turn_index: int = 0,
        *,
        done: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._cp_id = str(checkpoint_id)
        self._index = int(index)
        self._title = str(title or f"Чекпоинт #{index}")
        self._summary = str(summary or "")
        self._turn_index = int(turn_index)
        self._done = bool(done)
        self.add_class("round-card")

    @property
    def checkpoint_id(self) -> str:
        return self._cp_id

    @property
    def turn_index(self) -> int:
        return self._turn_index

    @property
    def index(self) -> int:
        return self._index

    def compose(self) -> ComposeResult:
        accent = _accent_color()
        title_line = Text()
        title_line.append("◆ ", style=accent)
        title_line.append(f"Чекпоинт #{self._index}", style=f"bold {accent}")
        title_line.append("  ·  ", style="#6B7280")
        title_line.append(self._title, style="#E5E7EB")
        yield Static(title_line, classes="deepcp-title")

        if self._summary:
            yield Static(Text(self._summary, style="#9CA3AF"),
                         classes="deepcp-summary")

        yield Horizontal(
            Button("↺ Откат", id=f"deepcp-rollback-{self._cp_id}",
                   classes="deepcp-rollback"),
            Button("▶ Продолжить", id=f"deepcp-continue-{self._cp_id}",
                   classes="deepcp-continue"),
            classes="deepcp-buttons",
        )

    def mark_done(self, note: str = "") -> None:
        """Disable both buttons after the checkpoint is consumed.

        Keeps the card in the stream as history but prevents the user from
        hitting the same checkpoint twice (which would be confusing — the
        history has already been trimmed).
        """
        self._done = True
        try:
            for btn_id in (f"deepcp-rollback-{self._cp_id}",
                           f"deepcp-continue-{self._cp_id}"):
                try:
                    btn = self.query_one(f"#{btn_id}", Button)
                    btn.disabled = True
                except Exception:
                    pass
            if note:
                self.mount(Static(Text(f"✓ {note}", style="#10B981"),
                                  classes="deepcp-summary"))
        except Exception:
            pass
