"""Панель чата Lorne (пакет). Публичный API — :class:`AIChatPanel` и сообщения."""
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

from ._css import AI_CHAT_PANEL_CSS
from ._messages import (
    ChatSubmitted,
    ModelChanged,
    ModeToggled,
    StopRequested,
    RollbackRequested,
    DeepCheckpointAction,
)
from ._blocks import AssistantMessageBlock, UserMessageBlock
from ._helpers import _split_thoughts_and_body, _format_path_for_chip, _syntax_theme
from ._mixin_setup import AIChatPanelSetupMixin
from ._mixin_stream import AIChatPanelStreamMixin
from ._mixin_events import AIChatPanelEventsMixin
from ._accent_dialog import _AccentPaletteDialog


class AIChatPanel(AIChatPanelSetupMixin, AIChatPanelStreamMixin, AIChatPanelEventsMixin, Vertical):
    """Центральная панель чата: ``VerticalScroll`` + при необходимости ``RichLog`` воркеров.

    Модели/режимы/метрики — состояние внутри; наружу — :class:`ChatSubmitted` и др.
    """

    BINDINGS = [
        Binding("ctrl+enter", "submit_chat", "Send", show=False),
    ]

    DEFAULT_CSS = AI_CHAT_PANEL_CSS


def _merge_ai_chat_mixin_decorators(panel_cls: type) -> None:
    """Copy ``@on`` metadata from plain mixins onto the widget's ``_decorated_handlers``.

    Textual's ``_MessagePumpMeta`` only inspects the class body being defined; mixin
    classes use the default metaclass, so their ``_textual_on`` methods never get
    registered unless we merge them here (send / attach / selects / downloads, …).
    """
    existing = dict(panel_cls.__dict__.get("_decorated_handlers") or {})
    for mixin in (AIChatPanelSetupMixin, AIChatPanelStreamMixin, AIChatPanelEventsMixin):
        for _name, fn in mixin.__dict__.items():
            if not callable(fn):
                continue
            for msg_type, selectors in getattr(fn, "_textual_on", ()) or ():
                existing.setdefault(msg_type, []).append((fn, selectors))
    panel_cls._decorated_handlers = existing  # type: ignore[attr-defined]


_merge_ai_chat_mixin_decorators(AIChatPanel)


__all__ = [
    "AIChatPanel",
    "ChatSubmitted",
    "ModelChanged",
    "ModeToggled",
    "StopRequested",
    "RollbackRequested",
    "DeepCheckpointAction",
    "AssistantMessageBlock",
    "UserMessageBlock",
    "_AccentPaletteDialog",
]
