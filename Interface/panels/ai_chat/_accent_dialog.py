"""Accent colour palette modal."""
from __future__ import annotations

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.markdown import Markdown

from rich.text import Text

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Checkbox, Collapsible, DirectoryTree, Input, Label, RichLog, Select,
    Static, TextArea,
)

try:
    from textual.widgets import Markdown as MarkdownWidget
except ImportError:  # pragma: no cover
    MarkdownWidget = None  # type: ignore[misc, assignment]

try:
    from Interface.panels.creator_progress import CreatorProgressBlock
except Exception:  # pragma: no cover
    CreatorProgressBlock = None  # type: ignore[misc, assignment]

try:
    from Interface.panels.diff_block import (
        CodeDiffBlock,
        diff_stats as _diff_stats,
        read_before_after_texts as _read_before_after_texts,
    )
except Exception:  # pragma: no cover
    CodeDiffBlock = None  # type: ignore[misc, assignment]
    def _diff_stats(before: str, after: str) -> tuple[int, int]:  # type: ignore[misc]
        return 0, 0
    def _read_before_after_texts(path: str, snapshot_id):  # type: ignore[misc]
        return "", ""

try:
    from Interface.panels.deep_checkpoint import DeepCheckpointBlock
except Exception:  # pragma: no cover
    DeepCheckpointBlock = None  # type: ignore[misc, assignment]

try:
    from Interface.panels.tool_card import ToolCardBlock, PRETTY_TOOL_NAMES
except Exception:  # pragma: no cover
    ToolCardBlock = None  # type: ignore[misc, assignment]
    PRETTY_TOOL_NAMES = frozenset()  # type: ignore[assignment]

try:
    from Interface.panels.download_block import DownloadProgressBlock
except Exception:  # pragma: no cover
    DownloadProgressBlock = None  # type: ignore[misc, assignment]

from typing import List, Optional

from ._constants import _ACCENT_COLORS

class _AccentPaletteDialog(ModalScreen):
    from Interface.modal_style import MODAL_SHARED_CSS as _SHARED_CSS

    DEFAULT_CSS = _SHARED_CSS + """
    _AccentPaletteDialog { align: center middle; }
    #apd-container {
        width: 70;
        height: auto;
        max-height: 18;
    }
    #apd-title { height: auto; }
    #apd-container Horizontal {
        height: auto;
        layout: horizontal;
        margin: 0 0 1 0;
    }
    #apd-container Horizontal Button {
        min-width: 6;
        width: 6;
        height: 3;
        margin: 0 1 0 0;
        border: tall #2D2D3D;
    }
    #apd-cancel {
        min-width: 14;
        height: 3;
        margin: 1 0 0 0;
    }
    """

    def __init__(self, colors: List[str], callback) -> None:
        super().__init__()
        self._colors = list(colors)
        self._callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(id="apd-container", classes="modal-card"):
            yield Label("Палитра accent color", id="apd-title", classes="modal-title")
            with Horizontal():
                for i in range(0, min(8, len(self._colors))):
                    yield Button("  ", id=f"apd-pick-{i}")
            with Horizontal():
                for i in range(8, min(16, len(self._colors))):
                    yield Button("  ", id=f"apd-pick-{i}")
            with Horizontal():
                for i in range(16, min(24, len(self._colors))):
                    yield Button("  ", id=f"apd-pick-{i}")
            yield Button("Отмена", id="apd-cancel")

    def on_mount(self) -> None:
        from Interface.modal_style import apply_accent_to
        apply_accent_to(
            self,
            container_id="apd-container",
            title_id="apd-title",
            title_text="Палитра accent color",
        )
        for i, color in enumerate(self._colors):
            try:
                b = self.query_one(f"#apd-pick-{i}", Button)
                b.styles.background = color
            except Exception:
                pass

    @on(Button.Pressed)
    def on_click(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "apd-cancel":
            self.dismiss()
            if self._callback:
                self._callback(None)
            return
        if bid.startswith("apd-pick-"):
            try:
                i = int(bid.replace("apd-pick-", "", 1))
            except ValueError:
                return
            if 0 <= i < len(self._colors):
                self.dismiss()
                if self._callback:
                    self._callback(self._colors[i])
