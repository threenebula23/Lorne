"""Панель чата Lorne: поток сообщений (Markdown), вложения, метрики, режимы, стоп/откат.

Класс :class:`AIChatPanel` — основной виджет; сообщения Textual (``ChatSubmitted``, …)
улетают в ``LorneApp`` → ``agent``. Модуль большой: у новых публичных методов указывайте
*Параметры* / *Возвращает* в docstring."""
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


class ChatSubmitted(Message):
    """Событие: пользователь отправил сообщение (текст + опциональные вложения)."""

    def __init__(
        self,
        text: str,
        image_paths: Optional[List[Path]] = None,
        bubble_text: Optional[str] = None,
    ) -> None:
        """
        Параметры:
            text: Сырой текст (для агента).
            image_paths: Пути к изображениям в контекст.
            bubble_text: Текст пузыря; если None — копия ``text``.
        """
        super().__init__()
        self.text = text
        self.image_paths = list(image_paths or [])
        self.bubble_text = (bubble_text if bubble_text is not None else text)


class ModelChanged(Message):
    """Событие: пользователь сменил модель в селекторе."""

    def __init__(self, model_id: str) -> None:
        """
        Параметры:
            model_id: Идентификатор модели (как в списке OpenRouter/ollama).
        """
        super().__init__()
        self.model_id = model_id


class ModeToggled(Message):
    """Событие: смена режима (normal / creator / deep / agent / research)."""

    def __init__(self, mode: str) -> None:
        """
        Параметры:
            mode: Имя режима (строгое значение, как в UI).
        """
        super().__init__()
        self.mode = mode


class StopRequested(Message):
    """Событие: запрошена остановка агента (кнопка Stop)."""
    pass


class RollbackRequested(Message):
    """Событие: откат к снимку до пользовательского хода ``turn_index`` (с нуля)."""

    def __init__(self, turn_index: int) -> None:
        """
        Параметры:
            turn_index: Индекс хода (как в логике ``checkpoint``/чата).
        """
        super().__init__()
        self.turn_index = int(turn_index)


class DeepCheckpointAction(Message):
    """Событие: нажата кнопка на карточке чекпоинта Deep Solver (откат / продолжить)."""

    def __init__(self, cp_id: str, action: str) -> None:
        """
        Параметры:
            cp_id: Идентификатор снимка.
            action: Ключ действия (как в ``agent.handle_deep_checkpoint``).
        """
        super().__init__()
        self.cp_id = str(cp_id)
        self.action = str(action)


class ChatFilePickerScreen(ModalScreen[Optional[Path]]):
    """Модальное дерево файлов проекта — выбор файла для контекста или изображения."""

    from Interface.modal_style import MODAL_SHARED_CSS as _SHARED_CSS

    DEFAULT_CSS = _SHARED_CSS + """
    ChatFilePickerScreen { align: center middle; }
    #chatfp {
        width: 88%;
        height: 86%;
    }
    #chatfp-title {
        height: auto;
    }
    #chatfp-nav { height: 3; layout: horizontal; margin: 0 0 1 0; }
    #chatfp-nav Button {
        min-width: 12;
        margin: 0 1 0 0;
        height: 3;
    }
    #chatfp-path {
        width: 1fr;
        background: #0D0D0D;
        color: #E5E7EB;
        border: solid #2D2D3D;
    }
    #chatfp-tree {
        height: 1fr;
        background: #12121A;
        border: solid #2D2D3D;
    }
    #chatfp-actions { height: 3; layout: horizontal; margin: 1 0 0 0; }
    #chatfp-actions Button {
        min-width: 18;
        margin: 0 1 0 0;
        height: 3;
    }
    """

    def __init__(self, start_dir: Path) -> None:
        super().__init__()
        self._start_dir = start_dir.expanduser().resolve()
        self._selected_dir = self._start_dir
        self._picked_file: Optional[Path] = None
        self._root = Path("/")

    def compose(self) -> ComposeResult:
        with Vertical(id="chatfp", classes="modal-card"):
            yield Label(
                "Выберите файл (изображения — во вложения, остальное — в контекст)",
                id="chatfp-title",
                classes="modal-title",
            )
            with Horizontal(id="chatfp-nav"):
                yield Button("Корень", id="chatfp-root")
                yield Button("Домой", id="chatfp-home")
                yield Button("Вверх", id="chatfp-up")
                yield Button("Проект", id="chatfp-proj")
                yield Input(str(self._start_dir), id="chatfp-path")
            yield DirectoryTree(str(self._root), id="chatfp-tree")
            with Horizontal(id="chatfp-actions"):
                yield Button("Выбрать файл", id="chatfp-open", variant="primary")
                yield Button("Отмена", id="chatfp-cancel")

    def on_mount(self) -> None:
        from Interface.modal_style import apply_accent_to
        apply_accent_to(
            self,
            container_id="chatfp",
            title_id="chatfp-title",
            title_text="Выберите файл (изображения — во вложения, остальное — в контекст)",
        )
        self._go_to(self._start_dir)

    def _go_to(self, target: Path) -> None:
        try:
            target = target.expanduser().resolve()
            if not target.exists():
                return
            if target.is_file():
                target = target.parent
            self._selected_dir = target
            tree = self.query_one("#chatfp-tree", DirectoryTree)
            try:
                tree.path = str(target)
                tree.root.expand()
            except Exception:
                tree.remove()
                container = self.query_one("#chatfp", Vertical)
                actions = self.query_one("#chatfp-actions", Horizontal)
                container.mount(DirectoryTree(str(target), id="chatfp-tree"), before=actions)
            self.query_one("#chatfp-path", Input).value = str(target)
        except Exception:
            pass

    @on(DirectoryTree.DirectorySelected, "#chatfp-tree")
    def on_dir(self, event: DirectoryTree.DirectorySelected) -> None:
        self._selected_dir = event.path
        self._picked_file = None
        self.query_one("#chatfp-path", Input).value = str(event.path)

    @on(DirectoryTree.FileSelected, "#chatfp-tree")
    def on_file(self, event: DirectoryTree.FileSelected) -> None:
        self._picked_file = event.path
        self.query_one("#chatfp-path", Input).value = str(event.path)

    @on(Button.Pressed, "#chatfp-open")
    def on_open(self) -> None:
        if self._picked_file and self._picked_file.is_file():
            self.dismiss(self._picked_file.resolve())
            return
        raw = (self.query_one("#chatfp-path", Input).value or "").strip()
        if raw:
            p = Path(raw).expanduser()
            if p.is_file():
                self.dismiss(p.resolve())
                return
        self.notify("Укажите файл в дереве или полный путь к файлу", severity="warning")

    @on(Button.Pressed, "#chatfp-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#chatfp-root")
    def on_root(self) -> None:
        self._go_to(Path("/"))

    @on(Button.Pressed, "#chatfp-home")
    def on_home(self) -> None:
        self._go_to(Path.home())

    @on(Button.Pressed, "#chatfp-up")
    def on_up(self) -> None:
        self._go_to(self._selected_dir.parent)

    @on(Button.Pressed, "#chatfp-proj")
    def on_proj(self) -> None:
        self._go_to(self._start_dir)

    @on(Input.Submitted, "#chatfp-path")
    def on_path_submit(self, event: Input.Submitted) -> None:
        value = (event.value or "").strip()
        if value:
            self._go_to(Path(value).expanduser())
