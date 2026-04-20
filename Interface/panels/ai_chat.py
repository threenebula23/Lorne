"""AI Chat — центр: поток сообщений (Markdown), вложения над вводом, метрики раунда."""
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
    def __init__(
        self,
        text: str,
        image_paths: Optional[List[Path]] = None,
        bubble_text: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.text = text
        self.image_paths = list(image_paths or [])
        self.bubble_text = (bubble_text if bubble_text is not None else text)


class ModelChanged(Message):
    def __init__(self, model_id: str) -> None:
        super().__init__()
        self.model_id = model_id


class ModeToggled(Message):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode


class StopRequested(Message):
    pass


class RollbackRequested(Message):
    """Откат диалога к снимку до указанного пользовательского хода (индекс с нуля)."""

    def __init__(self, turn_index: int) -> None:
        super().__init__()
        self.turn_index = int(turn_index)


class DeepCheckpointAction(Message):
    """User clicked Откат / Продолжить on a Deep Solver checkpoint card."""

    def __init__(self, cp_id: str, action: str) -> None:
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


PURPLE = "#8B5CF6"
PURPLE_LIGHT = "#A78BFA"
GRAY = "#6B7280"
GREEN = "#10B981"
RED = "#EF4444"
YELLOW = "#F59E0B"
DIM = "#4B5563"
BLUE = "#3B82F6"
CYAN = "#06B6D4"

MODES = ["Normal", "Creator", "Agent", "Research", "Deep"]
MARKDOWN_SYNTAX_THEME_MAP = {
    "monokai": "monokai",
    "dracula": "dracula",
    "github_dark": "github-dark",
    "github_light": "github-light",
    "vs_dark": "vscode-dark",
    "vscode_dark": "vscode-dark",
    "nord": "nord",
    "one_dark": "one-dark",
    "one_light": "one-light",
    "material": "material",
    "zenburn": "zenburn",
    "solarized_dark": "solarized-dark",
    "solarized_light": "solarized-light",
}

_SYNTAX_OPTIONS = [
    ("Monokai", "monokai"),
    ("Dracula", "dracula"),
    ("GitHub Dark", "github_dark"),
    ("GitHub Light", "github_light"),
    ("VS Dark", "vs_dark"),
    ("Nord", "nord"),
    ("One Dark", "one_dark"),
    ("One Light", "one_light"),
    ("Material", "material"),
    ("Zenburn", "zenburn"),
    ("Solarized Dark", "solarized_dark"),
    ("Solarized Light", "solarized_light"),
]

_ACCENT_COLORS = [
    "#8B5CF6", "#A78BFA", "#7C3AED", "#6366F1", "#3B82F6", "#06B6D4", "#10B981", "#22C55E",
    "#84CC16", "#EAB308", "#F59E0B", "#F97316", "#EF4444", "#EC4899", "#D946EF", "#14B8A6",
    "#0EA5E9", "#2563EB", "#4F46E5", "#9333EA", "#DB2777", "#DC2626", "#111827", "#FFFFFF",
]

_WRITE_TOOLS = frozenset({
    "edit_file", "write_file", "replace_file_lines", "insert_file_lines",
    "create_code_file", "append_code_snippet",
})

_WEB_TOOLS = frozenset({"web_search", "web_fetch", "web_search_and_read"})

_CHAT_IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})

def _split_thoughts_and_body(text: str) -> tuple[list[str], str]:
    """Извлекает блоки рассуждений (как в graph_runner / message_utils)."""
    try:
        from Agent.message_utils import extract_thought_segments
        return extract_thought_segments(text or "")
    except Exception:
        thoughts: list[str] = []

        def _sub(m: re.Match) -> str:
            inner = (m.group(1) or "").strip()
            if inner:
                thoughts.append(inner)
            return ""

        body = re.compile(r"<thought>([\s\S]*?)</thought>", re.IGNORECASE).sub(_sub, text or "")
        return thoughts, (body or "").strip()


def _format_path_for_chip(full_path: str, max_len: int = 58) -> str:
    """Readable parent path for context chips (middle truncation)."""
    try:
        p = Path(full_path).expanduser().resolve()
        s = str(p.parent)
    except Exception:
        s = str(Path(full_path).parent)
    s = s.replace("\n", " ")
    if len(s) <= max_len:
        return s
    keep = max_len - 1
    left = keep // 2
    right = keep - left
    return s[:left] + "…" + s[-right:]


def _syntax_theme() -> str:
    try:
        from Interface.ui_prefs import load_prefs
        pref = str(load_prefs().get("syntax_theme", "monokai"))
        return MARKDOWN_SYNTAX_THEME_MAP.get(pref, "monokai")
    except Exception:
        return "monokai"


class AssistantMessageBlock(Vertical):
    """Ответ ассистента: Markdown + кнопка копирования + футер."""

    DEFAULT_CSS = """
    AssistantMessageBlock {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1 1 1;
        background: #12121a;
        border: round #2D2D3D;
    }
    AssistantMessageBlock .assistant-md {
        height: auto;
        margin: 0 0 1 0;
    }
    AssistantMessageBlock .assistant-footer {
        height: auto;
        color: #6B7280;
        margin-top: 1;
    }
    AssistantMessageBlock .copy-row {
        height: auto;
        layout: horizontal;
        margin-top: 1;
    }
    AssistantMessageBlock .copy-row Button {
        min-width: 18;
        height: 3;
        content-align: center middle;
    }
    """

    def __init__(self, plain_copy: str, footer: str, copy_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._plain = plain_copy
        self._footer = footer or ""
        self._copy_id = copy_id

    def compose(self) -> ComposeResult:
        theme = _syntax_theme()
        body = (self._plain or "").strip()[:120_000]
        if MarkdownWidget is not None:
            yield MarkdownWidget(body, classes="assistant-md")
        else:
            yield Static(Markdown(body, code_theme=theme), classes="assistant-md")
        with Horizontal(classes="copy-row"):
            yield Button("Копировать ответ", id=f"copy-assistant-{self._copy_id}", variant="default")
        if self._footer.strip():
            yield Static(self._footer, classes="assistant-footer")

    @on(Button.Pressed)
    def _copy_local(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid != f"copy-assistant-{self._copy_id}":
            return
        text = self._plain or ""
        try:
            fn = getattr(self.app, "copy_to_clipboard", None)
            if callable(fn):
                fn(text)
                self.notify("Скопировано в буфер")
                return
        except Exception:
            pass
        self.notify("Буфер недоступен в этом терминале", severity="warning")


class UserMessageBlock(Vertical):
    DEFAULT_CSS = """
    UserMessageBlock {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
        background: #1a1528;
        border-left: outer #8B5CF6;
    }
    UserMessageBlock .user-rollback-row {
        height: auto;
        margin-top: 1;
    }
    UserMessageBlock .user-rollback-row Button {
        min-width: 28;
        background: #1F2430;
        color: #9CA3AF;
        border: tall #2D2D3D;
    }
    UserMessageBlock .user-rollback-row Button:hover {
        background: #272D3A;
        color: #D1D5DB;
    }
    """

    def __init__(self, text: str, turn_index: int = -1, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text
        self._turn_index = int(turn_index)
        self._name_static: Optional[Static] = None

    def _accent(self) -> str:
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import get_theme
            prefs = load_prefs()
            theme = get_theme(str(prefs.get("theme", "Purple Dark")))
            return str(prefs.get("accent_color") or theme.get("accent") or PURPLE)
        except Exception:
            return PURPLE

    def compose(self) -> ComposeResult:
        accent = self._accent()
        self._name_static = Static(Text("Вы", style=f"bold {accent}"))
        yield self._name_static
        yield Static(Text(self._text, style="#E5E7EB"))
        if self._turn_index >= 0:
            with Horizontal(classes="user-rollback-row"):
                yield Button(
                    "Откат к состоянию до этого запроса",
                    id=f"rollback-btn-{self._turn_index}",
                    variant="default",
                )

    def on_mount(self) -> None:
        self.refresh_accent()

    def refresh_accent(self) -> None:
        accent = self._accent()
        try:
            self.styles.border_left = ("outer", accent)
        except Exception:
            pass
        if self._name_static is not None:
            try:
                self._name_static.update(Text("Вы", style=f"bold {accent}"))
            except Exception:
                pass

    @on(Button.Pressed)
    def _on_rollback_press(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("rollback-btn-"):
            try:
                idx = int(bid.replace("rollback-btn-", "", 1))
            except ValueError:
                return
            try:
                self.app.post_message(RollbackRequested(idx))
            except Exception:
                self.post_message(RollbackRequested(idx))


class AIChatPanel(Vertical):
    """Чат: основной поток — виджеты; воркер — RichLog."""

    BINDINGS = [
        Binding("ctrl+enter", "submit_chat", "Send", show=False),
    ]

    DEFAULT_CSS = """
    AIChatPanel {
        height: 1fr;
    }
    #chat-thread-label {
        dock: top;
        height: 1;
        background: #151520;
        color: #A78BFA;
        text-style: bold;
        padding: 0 1;
    }
    #chat-log-region {
        height: 1fr;
        min-height: 8;
        border-top: solid #2D2D3D;
        border-bottom: solid #2D2D3D;
    }
    #main-chat-stream {
        height: 1fr;
        background: #0D0D0D;
        padding: 0 1;
    }
    #chat-messages-worker {
        height: 1fr;
        background: #0D0D0D;
        padding: 0 1;
    }
    #attachment-strip {
        height: auto;
        min-height: 1;
        layout: horizontal;
        margin: 0 0 1 0;
        overflow-x: auto;
    }
    .attach-chip {
        height: auto;
        min-height: 3;
        min-width: 12;
        margin: 0 1 0 0;
        background: #2D2D3D;
        color: #E5E7EB;
        border: solid #3D3D4D;
        text-align: left;
        content-align: left middle;
    }
    .attach-chip:hover {
        background: #8B5CF6;
    }
    #deep-status-bar {
        height: 0;
        min-height: 0;
        display: none;
        padding: 0 1;
        margin: 0 0 1 0;
        background: #12121A;
        border-left: thick #8B5CF6;
        color: #E5E7EB;
    }
    #deep-status-bar.-active {
        height: auto;
        min-height: 1;
        display: block;
    }
    #ctx-meter-row {
        height: auto;
        min-height: 2;
        layout: horizontal;
        margin: 0 0 1 0;
        padding: 0 0 0 0;
    }
    #ctx-progress-visual {
        width: 1fr;
        min-width: 18;
        height: auto;
        min-height: 1;
        color: #9CA3AF;
    }
    #ctx-session-line {
        width: auto;
        min-width: 10;
        height: auto;
        min-height: 1;
        color: #6B7280;
        text-align: right;
        content-align: right middle;
    }
    #chat-input-area {
        dock: bottom;
        height: auto;
        max-height: 40;
        background: #0D0D0D;
        padding: 0 1 1 1;
    }
    #creator-progress-slot {
        height: auto;
        width: 100%;
        padding: 0;
        margin: 0 0 1 0;
    }
    #creator-progress-slot.hidden {
        display: none;
    }
    #chat-input {
        border: solid #2D2D3D;
        background: #0D0D0D;
        color: #E5E7EB;
    }
    #chat-controls {
        height: auto;
        layout: horizontal;
        margin-top: 0;
    }
    #send-btn {
        min-width: 14;
        margin: 0 1 0 0;
    }
    #attach-file-btn {
        min-width: 16;
        margin: 0 1 0 0;
    }
    #model-select {
        width: 2fr;
        min-width: 28;
        max-width: 100%;
    }
    #mode-select {
        width: 1fr;
        min-width: 18;
        max-width: 100%;
        margin: 0 1 0 0;
    }
    #stop-btn {
        display: none;
    }
    #stop-btn.visible {
        display: block;
    }
    #custom-models-line {
        display: none;
    }
    /* ── Unified settings spacing ──────────────────────────────────
       Every field in every settings tab goes through ``.settings-row`` and
       every button row goes through ``.settings-button-row``. By keeping
       the vertical gap (``margin-bottom: 1``) and padding identical across
       them, the tabs line up visually instead of looking like three
       different screens glued together. Do NOT override these margins in
       per-section CSS — rely on the spacing defined here. */
    .settings-row {
        height: auto;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 1fr 2fr;
        grid-gutter: 0 3;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    .settings-row-label {
        content-align: left middle;
        color: #E5E7EB;
        padding: 1 1;
        min-width: 18;
    }
    .settings-row Input, .settings-row Select {
        width: 100%;
        min-width: 14;
        height: 3;
    }
    .settings-row Checkbox {
        width: 100%;
        height: 3;
    }
    #sor-balance-display {
        height: auto;
        min-height: 3;
        color: #9CA3AF;
        padding: 1 2;
        background: #0D0D12;
        border: tall #2D2D3D;
    }
    .settings-section-title {
        text-style: bold;
        margin: 1 0 1 0;
        padding: 0 1;
    }
    .settings-card {
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        background: #12121A;
        border: round #2D2D3D;
    }
    .settings-card-title {
        text-style: bold;
        margin: 0 0 1 0;
        padding: 0 0 1 0;
    }
    .settings-card-subtitle {
        color: #6B7280;
        margin: 0 0 1 0;
        padding: 0 1;
        text-style: italic;
    }
    .settings-hint {
        color: #6B7280;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    .settings-button-row {
        height: auto;
        layout: horizontal;
        margin: 1 0 0 0;
        padding: 0 1;
    }
    .settings-button-row Button {
        margin: 0 2 0 0;
        min-width: 24;
        height: 3;
        border: round #2D2D3D;
        padding: 0 2;
        text-style: bold;
    }
    .settings-action-btn {
        background: #1C1C26;
        color: #E5E7EB;
        border: round #2D2D3D;
    }
    .settings-action-btn:hover {
        background: #26263A;
    }
    .settings-action-btn--primary {
        background: #2A1F4D;
        color: #F3F4F6;
    }
    .settings-action-btn--primary:hover {
        background: #3B2F6B;
    }
    .settings-action-btn--success {
        background: #10321F;
        color: #A7F3D0;
    }
    .settings-action-btn--success:hover {
        background: #164C2E;
    }
    .settings-action-btn--error {
        background: #3A1313;
        color: #FCA5A5;
    }
    .settings-action-btn--error:hover {
        background: #561E1E;
    }
    .param-grid {
        height: auto;
        layout: grid;
        grid-size: 2 4;
        grid-rows: 7 7 7 7;
        grid-gutter: 2 3;
        margin: 1 0 1 0;
        padding: 0 1;
    }
    .param-cell {
        height: 7;
        layout: vertical;
        padding: 1 2;
        background: #0D0D12;
        border: tall #2D2D3D;
    }
    .param-cell-label {
        text-style: bold;
        height: 1;
    }
    .param-cell-hint {
        color: #6B7280;
        height: 1;
        text-style: italic;
    }
    .param-cell Input {
        width: 100%;
        height: 3;
        margin: 1 0;
    }
    .param-cell-wide {
        column-span: 2;
    }
    #sol-status {
        color: #9CA3AF;
        margin: 1 0 0 0;
    }
    #sol-model-list {
        color: #9CA3AF;
        margin: 1 0 0 0;
        padding: 1 2;
        background: #0D0D0D;
        border: solid #2D2D3D;
    }
    .stream-line {
        height: auto;
        margin: 0 0 0 0;
        color: #9CA3AF;
    }
    .file-changes-table {
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        background: #12121A;
        border: round #2D2D3D;
    }
    .sources-widget {
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        background: #12121A;
        border: round #2D2D3D;
    }
    Collapsible.round-card {
        height: auto;
        margin: 0 0 1 0;
        background: #12121A;
        border: round #2D2D3D;
        padding: 0 0 0 0;
    }
    Collapsible.round-card > CollapsibleTitle {
        padding: 0 1 0 1;
        height: auto;
        color: #E5E7EB;
    }
    Collapsible.round-card > Contents {
        padding: 1 1 1 1;
    }
    """

    def __init__(self, models: Optional[List[Dict]] = None,
                 current_model: str = "", **kwargs):
        super().__init__(**kwargs)
        self._models = models or []
        self._current_model = current_model
        self._current_mode = "Normal"
        self._context_used = 0
        self._context_total = 128_000
        self._worker_logs: Dict[str, List[str]] = {}
        self._view_worker: str = ""
        self._context_hints: List[str] = []
        self._last_render_key = ""
        self._last_render_ts = 0.0
        self._pending_images: List[Path] = []
        self._msg_seq = 0
        self._round_file_deltas: Dict[str, int] = {}
        self._round_file_changes: Dict[str, Dict[str, int]] = {}
        self._round_file_order: List[str] = []
        self._round_web_sources: List[Dict[str, str]] = []
        self._round_web_seen: set[str] = set()
        self._chip_epoch = 0
        self._lifetime_prompt = 0
        self._lifetime_completion = 0
        self._creator_progress: Optional[Any] = None

    def compose(self) -> ComposeResult:
        yield Static("Чат проекта", id="chat-thread-label")
        with Vertical(id="chat-log-region"):
            yield VerticalScroll(id="main-chat-stream")
            yield RichLog(id="chat-messages-worker", wrap=True, markup=False)
        yield Vertical(id="chat-input-area")

    def on_mount(self) -> None:
        self._build_input_area()
        self._add_welcome()
        try:
            self.query_one("#chat-messages-worker", RichLog).display = False
        except Exception:
            pass
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import SYNTAX_THEME_MAP, ensure_custom_textarea_themes
            prefs = load_prefs()
            if prefs.get("ollama_base_url"):
                os.environ.setdefault("OLLAMA_BASE_URL", str(prefs.get("ollama_base_url")))
            if prefs.get("ollama_api_key"):
                os.environ.setdefault("OLLAMA_API_KEY", str(prefs.get("ollama_api_key")))
            ta = self.query_one("#chat-input", TextArea)
            ensure_custom_textarea_themes(ta)
            ta.theme = SYNTAX_THEME_MAP.get(
                str(prefs.get("syntax_theme", "monokai")), "monokai",
            )
        except Exception:
            pass
        self._load_extra_models_from_prefs()
        self._update_custom_models_line()
        self._refresh_context_meter()

    def _main_stream(self) -> VerticalScroll:
        return self.query_one("#main-chat-stream", VerticalScroll)

    def _worker_visible_log(self) -> RichLog:
        return self.query_one("#chat-messages-worker", RichLog)

    def _ui_colors(self) -> Dict[str, str]:
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import get_theme
            prefs = load_prefs()
            theme = get_theme(str(prefs.get("theme", "Purple Dark")))
            accent = str(prefs.get("accent_color") or theme.get("accent") or PURPLE)
            return {
                "accent": accent,
                "accent2": str(theme.get("accent2", PURPLE_LIGHT)),
                "fg": str(theme.get("fg", "#E5E7EB")),
                "fg2": str(theme.get("fg2", GRAY)),
            }
        except Exception:
            return {"accent": PURPLE, "accent2": PURPLE_LIGHT, "fg": "#E5E7EB", "fg2": GRAY}

    def _mount_main(self, widget: Vertical | Static | AssistantMessageBlock | UserMessageBlock) -> None:
        stream = self._main_stream()
        stream.mount(widget)
        try:
            stream.scroll_end(animate=False)
        except Exception:
            pass

    def _build_input_area(self) -> None:
        area = self.query_one("#chat-input-area", Vertical)
        area.mount(Horizontal(id="attachment-strip"))

        model_options = []
        for m in self._models:
            name = m.get("name", m.get("id", "?"))
            mid = m.get("id", name)
            short_name = name
            if "/" in short_name:
                short_name = short_name.split("/")[-1]
            if len(short_name) > 25:
                short_name = short_name[:22] + "…"
            model_options.append((short_name, mid))
        if not model_options:
            model_options = [("Default", "default")]

        mode_options = [(m, m.lower()) for m in MODES]

        area.mount(Vertical(id="creator-progress-slot"))
        # Deep Solver status badge — shows elapsed time / checkpoint count
        # while a Deep run is live. Hidden by default via CSS.
        area.mount(Static("", id="deep-status-bar"))
        area.mount(TextArea(
            "",
            id="chat-input",
            soft_wrap=True,
            show_line_numbers=False,
        ))
        area.mount(Horizontal(
            Static("", id="ctx-progress-visual"),
            Static("", id="ctx-session-line"),
            id="ctx-meter-row",
        ))
        area.mount(Horizontal(
            Button("Отправить", id="send-btn", variant="primary"),
            Button("Добавить файл…", id="attach-file-btn", variant="default"),
            Select(model_options, value=self._current_model or "default",
                   id="model-select", allow_blank=False),
            Select(mode_options, value="normal", id="mode-select", allow_blank=False),
            Button("Стоп", id="stop-btn"),
            id="chat-controls",
        ))

    def _accent(self) -> str:
        try:
            return self._ui_colors()["accent"]
        except Exception:
            return PURPLE

    def _settings_row(self, content, label: str, widget) -> None:  # type: ignore[override]
        content.mount(Horizontal(
            Label(Text(label, style=f"bold {self._accent()}"), classes="settings-row-label"),
            widget,
            classes="settings-row",
        ))

    def _settings_title(self, text: str) -> Label:
        return Label(Text(text, style=f"bold {self._accent()}"), classes="settings-card-title")

    def _section_title(self, text: str) -> Label:
        return Label(Text(text, style=f"bold {self._accent()}"), classes="settings-section-title")

    def render_settings_into(self, scroll: VerticalScroll, section: str) -> None:
        """Fill a workspace settings tab (widgets may live outside this panel)."""
        sec = (section or "").strip().lower()
        if sec not in {"personalization", "agents", "openrouter", "ollama"}:
            sec = "personalization"
        try:
            scroll.remove_children()
        except Exception:
            for w in list(scroll.children):
                w.remove()
        self._render_settings_tab(sec, scroll)

    def _render_settings_tab(self, tab: str, content: VerticalScroll) -> None:
        if tab == "personalization":
            self._render_personalization_settings(content)
        elif tab == "agents":
            self._render_agents_settings(content)
        elif tab == "openrouter":
            self._render_openrouter_settings(content)
        elif tab == "ollama":
            self._render_ollama_settings(content)

    def _render_personalization_settings(self, content: VerticalScroll) -> None:
        from Interface.ui_prefs import load_prefs
        from Interface.themes import DARK_THEMES, LIGHT_THEMES

        prefs = load_prefs()
        theme_options = [(f"🌙 {t}", t) for t in DARK_THEMES] + [(f"☀️ {t}", t) for t in LIGHT_THEMES]
        theme = str(prefs.get("theme", "Purple Dark"))
        available_theme_ids = {t[1] for t in theme_options}
        if theme not in available_theme_ids and theme_options:
            theme = str(theme_options[0][1])
        density = str(prefs.get("density", "normal"))
        syntax = str(prefs.get("syntax_theme", "monokai"))
        accent = str(prefs.get("accent_color", "#8B5CF6"))
        content.mount(self._section_title("Внешний вид интерфейса"))
        self._settings_row(
            content, "Тема",
            Select(theme_options, value=theme, id="sp-theme", allow_blank=False),
        )
        self._settings_row(
            content, "Плотность",
            Select(
                [("Компактный", "compact"), ("Обычный", "normal"), ("Крупный", "spacious")],
                value=density if density in ("compact", "normal", "spacious") else "normal",
                id="sp-density",
                allow_blank=False,
            ),
        )
        self._settings_row(
            content, "Подсветка",
            Select(_SYNTAX_OPTIONS, value=syntax, id="sp-syntax", allow_blank=False),
        )
        self._settings_row(
            content, "Accent",
            Input(value=accent, id="sp-accent", placeholder="#8B5CF6"),
        )
        content.mount(Horizontal(
            Button("🎨 Применить цвет", id="sp-apply-accent",
                   classes="settings-action-btn settings-action-btn--primary",
                   variant="primary"),
            Button("🎲 Открыть палитру", id="sp-open-palette",
                   classes="settings-action-btn", variant="default"),
            classes="settings-button-row",
        ))

    def _render_agents_settings(self, content: VerticalScroll) -> None:
        from Interface.ui_prefs import load_prefs

        prefs = load_prefs()
        prof = os.getenv("TCA_PROFILE", "balanced").lower()
        if prof not in ("fast", "balanced", "quality"):
            prof = "balanced"

        # ── Card 1: profile + tool toggles ──────────────────────────────
        tools_card = Vertical(classes="settings-card", id="sa-tools-card")
        content.mount(tools_card)
        tools_card.mount(self._settings_title("Профиль агента и тулы"))
        tools_card.mount(Label(
            "Эти настройки применяются во всех режимах (Normal / Agent / Creator / Research) "
            "и ко всем моделям — локальным и удалённым.",
            classes="settings-card-subtitle",
        ))
        self._settings_row(
            tools_card, "Профиль TCA",
            Select(
                [("Fast", "fast"), ("Balanced", "balanced"), ("Quality", "quality")],
                value=prof,
                id="sa-profile",
                allow_blank=False,
            ),
        )
        self._settings_row(
            tools_card, "Browser tools",
            Checkbox(
                "Включить (headless) в Agent mode",
                value=bool(prefs.get("browser_tools_enabled", True)),
                id="sa-browser",
            ),
        )
        self._settings_row(
            tools_card, "Playwright Py",
            Checkbox(
                "Включить Python Playwright в Agent mode",
                value=bool(prefs.get("playwright_python_enabled", False)),
                id="sa-playwright",
            ),
        )
        self._settings_row(
            tools_card, "Кастом-тулы",
            Checkbox(
                "Подключать RAG / planning / interpreter / thinking",
                value=bool(prefs.get("custom_tools_enabled", True)),
                id="sa-custom-tools",
            ),
        )

        # ── Card 2: Creator orchestration ──────────────────────────────
        orch_card = Vertical(classes="settings-card", id="sa-orch-card")
        content.mount(orch_card)
        orch_card.mount(self._settings_title("Creator — оркестрация"))
        orch_card.mount(Label(
            "Parallel — воркеры запускаются одновременно. Pipeline — последовательно, "
            "передавая результат дальше. Auto — оркестратор сам выбирает режим под задачу.",
            classes="settings-card-subtitle",
        ))
        orch_mode = str(prefs.get("orchestration_mode", "auto")).lower()
        if orch_mode not in ("parallel", "pipeline", "auto"):
            orch_mode = "auto"
        self._settings_row(
            orch_card, "Режим",
            Select(
                [("Auto", "auto"), ("Parallel", "parallel"), ("Pipeline", "pipeline")],
                value=orch_mode, id="sa-orch-mode", allow_blank=False,
            ),
        )
        self._settings_row(
            orch_card, "Макс. воркеров",
            Input(
                value=str(int(prefs.get("orchestration_max_workers", 4) or 4)),
                id="sa-orch-max-workers", placeholder="4",
            ),
        )

        # ── Card 3: Research mode ──────────────────────────────────────
        res_card = Vertical(classes="settings-card", id="sa-research-card")
        content.mount(res_card)
        res_card.mount(self._settings_title("Research mode"))
        res_card.mount(Label(
            "Параметры веб-ресёрча: сколько источников собирать, сколько раундов углубления, "
            "и нужно ли тянуть полные страницы (web_fetch) вслед за web_search.",
            classes="settings-card-subtitle",
        ))
        self._settings_row(
            res_card, "Макс. источников",
            Input(
                value=str(int(prefs.get("research_max_sources", 6) or 6)),
                id="sa-research-max-sources", placeholder="6",
            ),
        )
        self._settings_row(
            res_card, "Раундов углубления",
            Input(
                value=str(int(prefs.get("research_max_rounds", 3) or 3)),
                id="sa-research-max-rounds", placeholder="3",
            ),
        )
        self._settings_row(
            res_card, "Deep fetch",
            Checkbox(
                "Подгружать полные страницы (web_fetch) для топ-результатов",
                value=bool(prefs.get("research_deep_fetch", True)),
                id="sa-research-deep-fetch",
            ),
        )
        res_card.mount(Horizontal(
            Button("✓ Применить изменения", id="sa-apply",
                   classes="settings-action-btn settings-action-btn--primary",
                   variant="primary"),
            classes="settings-button-row",
        ))
        res_card.mount(Static("", id="sa-status"))

    def _render_openrouter_settings(self, content: VerticalScroll) -> None:
        from Interface.ui_prefs import load_prefs

        prefs = load_prefs()
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        masked = api_key if len(api_key) <= 8 else api_key[:8] + "…"
        content.mount(self._section_title("OpenRouter"))
        self._settings_row(
            content, "API key",
            Input(value=masked, password=True, id="sor-api-key", placeholder="sk-or-..."),
        )
        content.mount(Horizontal(
            Button("💾 Сохранить API key", id="sor-save-key",
                   classes="settings-action-btn settings-action-btn--primary",
                   variant="primary"),
            classes="settings-button-row",
        ))
        content.mount(self._section_title("Счёт OpenRouter"))
        try:
            from Interface.panels.usage_calendar import UsageCalendar
            content.mount(UsageCalendar(id="sor-usage-calendar"))
        except Exception:
            pass
        self._settings_row(
            content, "Статус",
            Static(
                "Нажмите «Проверить баланс», чтобы обновить данные календаря.",
                id="sor-balance-display",
            ),
        )
        content.mount(Horizontal(
            Button("🔍 Проверить баланс", id="sor-check-balance",
                   classes="settings-action-btn", variant="default"),
            classes="settings-button-row",
        ))
        self._settings_row(
            content, "Model ID",
            Input(id="sor-model-id", placeholder="provider/model-id"),
        )
        self._settings_row(
            content, "Название",
            Input(id="sor-model-name", placeholder="Например GPT-5 Mini"),
        )
        content.mount(Horizontal(
            Button("+ Добавить модель OpenRouter", id="sor-add-model",
                   classes="settings-action-btn settings-action-btn--success",
                   variant="success"),
            classes="settings-button-row",
        ))
        content.mount(Static("", id="sor-status"))
        lines = []
        for m in (prefs.get("openrouter_custom_models") or []):
            if isinstance(m, dict):
                lines.append(f"- {m.get('name') or m.get('id')} [{m.get('id')}]")
        content.mount(Static("Добавленные модели:\n" + ("\n".join(lines) if lines else "—"), id="sor-model-list"))

    def _param_cell(
        self,
        label: str, hint: str, widget_id: str, value: str, placeholder: str,
        wide: bool = False,
    ) -> Vertical:
        classes = "param-cell param-cell-wide" if wide else "param-cell"
        return Vertical(
            Label(Text(label, style=f"bold {self._accent()}"), classes="param-cell-label"),
            Input(value=str(value), id=widget_id, placeholder=placeholder),
            Label(hint, classes="param-cell-hint"),
            classes=classes,
        )

    def _render_ollama_settings(self, content: VerticalScroll) -> None:
        from Interface.ui_prefs import load_prefs

        prefs = load_prefs()
        base_url = str(prefs.get("ollama_base_url", "http://localhost:11434/v1"))
        api_key = str(prefs.get("ollama_api_key", ""))
        presets = prefs.get("ollama_presets") or {}
        if not isinstance(presets, dict) or not presets:
            presets = {
                "default": {
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "top_k": 40,
                    "repeat_penalty": 1.1,
                    "num_ctx": 32768,
                    "num_predict": 8192,
                    "stop": "",
                }
            }
        preset_name = "default" if "default" in presets else next(iter(presets.keys()))
        pv = presets.get(preset_name) if isinstance(presets.get(preset_name), dict) else {}

        # ── Card 1: connection ──────────────────────────────────────────
        conn_card = Vertical(classes="settings-card", id="sol-conn-card")
        content.mount(conn_card)
        conn_card.mount(self._settings_title("Подключение к Ollama"))
        conn_card.mount(Label(
            "Локальный или удалённый Ollama-сервер. Нативный клиент использует /api, "
            "fallback — OpenAI-совместимый /v1.",
            classes="settings-card-subtitle",
        ))
        self._settings_row(
            conn_card, "Base URL",
            Input(value=base_url, id="sol-base-url", placeholder="http://localhost:11434"),
        )
        self._settings_row(
            conn_card, "API key",
            Input(value=api_key, id="sol-api-key", password=True, placeholder="опционально"),
        )
        conn_card.mount(Horizontal(
            Button("💾 Сохранить подключение", id="sol-save-conn",
                   classes="settings-action-btn settings-action-btn--primary",
                   variant="primary"),
            Button("🔄 Обновить список моделей", id="sol-refresh",
                   classes="settings-action-btn", variant="default"),
            classes="settings-button-row",
        ))

        # ── Card 2: model + preset selection ────────────────────────────
        model_card = Vertical(classes="settings-card", id="sol-model-card")
        content.mount(model_card)
        model_card.mount(self._settings_title("Модель и пресет"))
        model_card.mount(Label(
            "Выберите модель из списка и пресет параметров. "
            "Пресет можно сохранить, а настройки — привязать к конкретной модели.",
            classes="settings-card-subtitle",
        ))
        self._settings_row(
            model_card, "Модель",
            Select(
                [("— сначала нажмите «Обновить» —", "")],
                id="sol-model-select", allow_blank=False,
            ),
        )
        self._settings_row(
            model_card, "Пресет",
            Select(
                [(str(k), str(k)) for k in presets.keys()],
                value=str(preset_name),
                id="sol-preset-select",
                allow_blank=False,
            ),
        )

        # ── Card 3: generation parameters ───────────────────────────────
        # Uniform "label left / input right" layout — same pattern as every
        # other settings card so the Ollama params line up with connection,
        # agent, personalization, etc.
        params_card = Vertical(classes="settings-card", id="sol-params-card")
        content.mount(params_card)
        params_card.mount(self._settings_title("Параметры генерации"))
        params_card.mount(Label(
            "Передаются Ollama напрямую. ``num_ctx``, ``top_k`` и ``repeat_penalty`` "
            "работают только через нативный клиент (fallback OpenAI-API их игнорирует).",
            classes="settings-card-subtitle",
        ))
        self._settings_row(
            params_card, "temperature",
            Input(value=str(pv.get("temperature", 0.2)),
                  id="sol-param-temperature", placeholder="0.2 · креативность"),
        )
        self._settings_row(
            params_card, "top_p",
            Input(value=str(pv.get("top_p", 0.9)),
                  id="sol-param-top-p", placeholder="0.9 · nucleus sampling"),
        )
        self._settings_row(
            params_card, "top_k",
            Input(value=str(pv.get("top_k", 40)),
                  id="sol-param-top-k", placeholder="40 · кандидаты"),
        )
        self._settings_row(
            params_card, "repeat_penalty",
            Input(value=str(pv.get("repeat_penalty", 1.1)),
                  id="sol-param-repeat-penalty", placeholder="1.1 · штраф за повторы"),
        )
        self._settings_row(
            params_card, "num_ctx",
            Input(value=str(pv.get("num_ctx", 32768)),
                  id="sol-param-num-ctx", placeholder="32768 · размер контекста"),
        )
        self._settings_row(
            params_card, "num_predict",
            Input(value=str(pv.get("num_predict", 8192)),
                  id="sol-param-num-predict", placeholder="8192 · макс. токенов ответа"),
        )
        self._settings_row(
            params_card, "stop",
            Input(value=str(pv.get("stop", "")),
                  id="sol-param-stop", placeholder="<|im_end|>, END"),
        )
        params_card.mount(Horizontal(
            Button("💾 Сохранить пресет", id="sol-save-preset",
                   classes="settings-action-btn", variant="default"),
            Button("✓ Применить к модели", id="sol-apply-model-settings",
                   classes="settings-action-btn settings-action-btn--primary",
                   variant="primary"),
            Button("+ Добавить модель", id="sol-add",
                   classes="settings-action-btn settings-action-btn--success",
                   variant="success"),
            classes="settings-button-row",
        ))
        params_card.mount(Static("", id="sol-status"))

        # ── Card 4: added models list ──────────────────────────────────
        list_card = Vertical(classes="settings-card", id="sol-list-card")
        content.mount(list_card)
        list_card.mount(self._settings_title("Добавленные Ollama модели"))
        lines: List[str] = []
        for m in (prefs.get("ollama_custom_models") or []):
            if isinstance(m, dict):
                label = m.get("label") or m.get("name") or "—"
                name = m.get("name") or ""
                ctx = m.get("ctx")
                suffix = f"  ·  ctx {ctx}" if ctx else ""
                lines.append(f"  • {label}  [{name}]{suffix}")
        list_card.mount(Static(
            "\n".join(lines) if lines else "  Пока нет добавленных моделей.",
            id="sol-model-list",
        ))

    def _update_env_file(self, key: str, value: str) -> None:
        p = Path.cwd() / ".env"
        lines: List[str] = []
        found = False
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith(f"{key}="):
                    lines.append(f"{key}={value}")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"{key}={value}")
        p.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _load_extra_models_from_prefs(self) -> None:
        try:
            from Interface.ui_prefs import load_prefs
        except Exception:
            return
        prefs = load_prefs()
        for m in (prefs.get("openrouter_custom_models") or []):
            if isinstance(m, dict):
                self.add_external_model(
                    str(m.get("id") or ""),
                    name=str(m.get("name") or ""),
                    ctx=int(m.get("ctx") or 128_000),
                    tier=str(m.get("tier") or "custom"),
                    source="openrouter",
                    activate=False,
                )
        for m in (prefs.get("ollama_custom_models") or []):
            if isinstance(m, dict):
                nm = str(m.get("name") or "")
                if not nm:
                    continue
                self.add_external_model(
                    f"ollama/{nm}",
                    name=str(m.get("label") or f"Ollama · {nm}"),
                    ctx=int(m.get("ctx") or 32_768),
                    tier="local",
                    source="ollama",
                    activate=False,
                )

    def _update_custom_models_line(self) -> None:
        # UI line for "additional models" was removed by user request; keep as no-op
        # so existing call sites continue to work harmlessly.
        return

    def _refresh_openrouter_list_view(self) -> None:
        try:
            from Interface.ui_prefs import load_prefs
            prefs = load_prefs()
            lines = []
            for m in (prefs.get("openrouter_custom_models") or []):
                if isinstance(m, dict):
                    lines.append(f"- {m.get('name') or m.get('id')} [{m.get('id')}]")
            self.app.query_one("#sor-model-list", Static).update(
                "Добавленные модели:\n" + ("\n".join(lines) if lines else "—")
            )
        except Exception:
            pass

    def _refresh_ollama_list_view(self) -> None:
        try:
            from Interface.ui_prefs import load_prefs
            prefs = load_prefs()
            lines = []
            for m in (prefs.get("ollama_custom_models") or []):
                if isinstance(m, dict):
                    lines.append(f"- {m.get('label') or m.get('name')}")
            self.app.query_one("#sol-model-list", Static).update(
                "Добавленные Ollama модели:\n" + ("\n".join(lines) if lines else "—")
            )
        except Exception:
            pass

    def _rebuild_attachment_strip(self) -> None:
        try:
            strip = self.query_one("#attachment-strip", Horizontal)
        except Exception:
            return
        for w in list(strip.children):
            w.remove()
        self._chip_epoch += 1
        ep = self._chip_epoch
        for i, p in enumerate(self._context_hints):
            name = Path(p).name
            if len(name) > 36:
                name = name[:33] + "…"
            hint = _format_path_for_chip(p)
            strip.mount(Button(
                f"Контекст: {name}\n{hint}\n(нажмите — убрать из контекста)",
                id=f"ctx_{ep}_{i}",
                classes="attach-chip",
            ))
        for j, img in enumerate(self._pending_images):
            name = img.name
            if len(name) > 32:
                name = name[:29] + "…"
            hint = _format_path_for_chip(str(img))
            strip.mount(Button(
                f"Изображение: {name}\n{hint}\n(нажмите — убрать)",
                id=f"img_{ep}_{j}",
                classes="attach-chip",
            ))

    def _add_welcome(self) -> None:
        colors = self._ui_colors()
        self._mount_main(Static(Text("TCA", style=f"bold {colors['accent']}")))
        self._mount_main(Static(Text(
            "Ответы в Markdown. Маленькие правки — replace_file_lines / insert_file_lines.",
            style=colors["fg2"],
        )))

    def set_view_worker(self, worker_id: Optional[str]) -> None:
        wid = (worker_id or "").strip()
        self._view_worker = wid
        stream = self.query_one("#main-chat-stream", VerticalScroll)
        wlog = self._worker_visible_log()
        label = self.query_one("#chat-thread-label", Static)
        try:
            ta = self.query_one("#chat-input", TextArea)
            for bid in (
                "#model-select",
                "#mode-select",
                "#send-btn",
                "#attach-file-btn",
            ):
                try:
                    self.query_one(bid).disabled = bool(wid)
                except Exception:
                    pass
            try:
                self.query_one("#ctx-meter-row", Horizontal).disabled = bool(wid)
            except Exception:
                pass
            ta.disabled = bool(wid)
        except Exception:
            pass

        if not wid:
            stream.display = True
            wlog.display = False
            label.update("Чат проекта")
        else:
            stream.display = False
            wlog.display = True
            label.update(Text(f"Воркер: {wid}", style=f"bold {self._ui_colors()['accent']}"))
            wlog.clear()
            wlog.write(Markdown(
                f"> Лог воркера **`{wid}`**. Чтобы писать в общий чат, выберите узел **«Общий чат»** слева внизу.\n",
            ))
            for line in self._worker_logs.get(wid, [])[-200:]:
                wlog.write(Markdown(line))

    def reset_round_file_metrics(self) -> None:
        self._round_file_deltas.clear()
        self._round_file_changes.clear()
        self._round_file_order.clear()

    def _mount_file_changes_table(self) -> None:
        """Render a compact table of files changed during the current turn."""
        if not self._round_file_changes:
            return
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import get_theme
            prefs = load_prefs()
            theme = get_theme(str(prefs.get("theme", "Purple Dark")))
            accent = str(prefs.get("accent_color") or theme.get("accent") or PURPLE)
        except Exception:
            accent = PURPLE

        # Column widths for the compact table.
        name_w = 42
        added_w = 8
        removed_w = 8

        paths = list(self._round_file_order) or list(self._round_file_changes.keys())
        rows: List[Tuple[str, int, int]] = []
        for p in paths[:20]:
            stats = self._round_file_changes.get(p) or {}
            rows.append((p, int(stats.get("added", 0)), int(stats.get("removed", 0))))
        extra = len(paths) - len(rows)

        body = Text()
        header = Text()
        header.append(" ", style="")
        header.append("Изменённые файлы", style=f"bold {accent}")
        header.append("   ", style="")
        header.append(f"({len(self._round_file_changes)} шт.)", style=f"{GRAY}")
        body.append_text(header)
        body.append("\n", style="")

        col_head = Text()
        col_head.append("ФАЙЛ".ljust(name_w), style=f"bold {GRAY}")
        col_head.append("  ", style="")
        col_head.append("+ДОБ.".rjust(added_w), style=f"bold {GREEN}")
        col_head.append("  ", style="")
        col_head.append("-УДАЛ.".rjust(removed_w), style=f"bold {RED}")
        body.append_text(col_head)
        body.append("\n", style="")
        body.append("─" * (name_w + added_w + removed_w + 4), style=GRAY)
        body.append("\n", style="")

        for p, added, removed in rows:
            name = Path(p).name or p
            if len(name) > name_w:
                name = name[: name_w - 1] + "…"
            body.append(name.ljust(name_w), style="#E5E7EB")
            body.append("  ", style="")
            body.append((f"+{added}").rjust(added_w), style=GREEN if added else GRAY)
            body.append("  ", style="")
            body.append((f"-{removed}").rjust(removed_w), style=RED if removed else GRAY)
            body.append("\n", style="")

        if extra > 0:
            body.append(f"… ещё {extra} файлов".center(name_w + added_w + removed_w + 4), style=GRAY)
            body.append("\n", style="")

        # Strip trailing newline for a tight card.
        if body.plain.endswith("\n"):
            body = body[:-1]

        count = len(self._round_file_changes)
        title = f"📂 Изменённые файлы  ·  {count} шт."
        card = Collapsible(
            Static(body),
            title=title,
            collapsed=True,
            classes="round-card",
        )
        self._mount_main(card)

    def reset_round_web_sources(self) -> None:
        self._round_web_sources.clear()
        self._round_web_seen.clear()

    def accumulate_web_tool_result(self, tool_name: str, result: Any) -> None:
        if tool_name not in _WEB_TOOLS or not isinstance(result, dict):
            return
        if result.get("error"):
            return
        for s in result.get("sources") or []:
            if not isinstance(s, dict):
                continue
            u = str(s.get("url") or "").strip()
            if not u or u in self._round_web_seen:
                continue
            self._round_web_seen.add(u)
            self._round_web_sources.append({
                "url": u,
                "title": str(s.get("title") or "")[:220],
            })

    def _append_web_sources_to_reply(self, text: str) -> str:
        """Legacy no-op: sources are rendered in their own widget now (see
        :meth:`_mount_sources_widget`). Kept to avoid breaking callers that
        still pipe assistant text through this hook."""
        return text or ""

    def _mount_sources_widget(self) -> None:
        """Render the collected web sources as a dedicated card below the
        final assistant reply. Works identically in every chat mode
        (Normal / Agent / Creator / Research)."""
        if not self._round_web_sources:
            return
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import get_theme
            prefs = load_prefs()
            theme = get_theme(str(prefs.get("theme", "Purple Dark")))
            accent = str(prefs.get("accent_color") or theme.get("accent") or PURPLE)
        except Exception:
            accent = PURPLE

        body = Text()
        header = Text()
        header.append(" ", style="")
        header.append("Источники", style=f"bold {accent}")
        header.append("   ", style="")
        header.append(f"({len(self._round_web_sources)} шт.)", style=f"{GRAY}")
        body.append_text(header)
        body.append("\n", style="")
        body.append("─" * 60, style=GRAY)
        body.append("\n", style="")

        for i, s in enumerate(self._round_web_sources[:30], start=1):
            u = s["url"]
            t = (s.get("title") or u).replace("\n", " ").strip()
            if len(t) > 90:
                t = t[:87] + "…"
            body.append(f"{i:>2}. ", style=f"bold {accent}")
            body.append(f"{t}\n", style="#E5E7EB")
            body.append(f"    {u}\n", style=GRAY)

        extra = len(self._round_web_sources) - 30
        if extra > 0:
            body.append(f"… ещё {extra} источников\n", style=GRAY)

        if body.plain.endswith("\n"):
            body = body[:-1]

        count = len(self._round_web_sources)
        title = f"🌐 Источники  ·  {count} шт."
        card = Collapsible(
            Static(body),
            title=title,
            collapsed=True,
            classes="round-card",
        )
        self._mount_main(card)
        self._round_web_sources.clear()
        self._round_web_seen.clear()

    def accumulate_tool_result(self, tool_name: str, result: Any) -> None:
        if tool_name not in _WRITE_TOOLS or not isinstance(result, dict):
            return
        if result.get("error"):
            return
        path = str(result.get("path") or result.get("file_path") or "")
        if not path:
            return
        delta = result.get("delta_total_lines")
        if delta is None:
            delta = result.get("lines_delta")
        try:
            d = int(delta) if delta is not None else 0
        except (TypeError, ValueError):
            d = 0
        self._round_file_deltas[path] = self._round_file_deltas.get(path, 0) + d

        snapshot_id = str(result.get("snapshot_id") or "")
        before, after = _read_before_after_texts(path, snapshot_id) if snapshot_id else ("", "")
        if not snapshot_id and result.get("action") == "created_file":
            try:
                after = Path(path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                after = ""
            before = ""

        added, removed = _diff_stats(before, after)
        if not added and not removed:
            delta_val = self._round_file_deltas.get(path, 0)
            if delta_val > 0:
                added, removed = delta_val, 0
            elif delta_val < 0:
                added, removed = 0, -delta_val

        agg = self._round_file_changes.setdefault(path, {"added": 0, "removed": 0})
        agg["added"] += max(0, added)
        agg["removed"] += max(0, removed)
        if path not in self._round_file_order:
            self._round_file_order.append(path)

        if CodeDiffBlock is not None and (before or after):
            if before != after:
                try:
                    action = str(result.get("action") or tool_name)
                    self._mount_main(CodeDiffBlock(path, before, after, action=action))
                except Exception:
                    pass

    def _footer_for_assistant(self, usage: Optional[Dict[str, Any]]) -> str:
        parts: List[str] = []
        pct = round(100 * self._context_used / self._context_total) if self._context_total > 0 else 0
        parts.append(
            f"Окно чата: ~{pct}% (~{self._context_used:,} / ~{self._context_total:,} ток.)",
        )
        lt = self._lifetime_prompt + self._lifetime_completion
        parts.append(
            f"Сессия Σ: ↑{self._lifetime_prompt:,} ↓{self._lifetime_completion:,} (всего ~{lt:,})",
        )
        if usage:
            est = bool(usage.get("_estimated"))
            inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            if inp or out:
                tag = "оценка по объёму ответа" if est else "данные провайдера"
                parts.append(f"Этот ответ: +{inp:,} вх. / +{out:,} вых. ({tag})")
        return "  │  ".join(parts)

    # ─── Public API ────────────────────────────────

    def add_user_message(self, text: str, turn_index: int = -1) -> None:
        self.reset_round_file_metrics()
        self.reset_round_web_sources()
        self._mount_main(UserMessageBlock(text, turn_index=turn_index))

    def rebuild_from_langchain_messages(self, msgs: List[Any]) -> None:
        """Перерисовать поток чата из списка LangChain-сообщений (после отката / загрузки сессии)."""
        try:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
        except ImportError:
            return

        stream = self._main_stream()
        for w in list(stream.children):
            w.remove()
        self._msg_seq = 0
        self._lifetime_prompt = 0
        self._lifetime_completion = 0
        self._last_render_key = ""
        hi = 0
        for m in msgs:
            if isinstance(m, SystemMessage):
                continue
            if isinstance(m, HumanMessage):
                self._mount_main(UserMessageBlock(str(m.content or ""), turn_index=hi))
                hi += 1
            elif isinstance(m, AIMessage):
                tcalls = getattr(m, "tool_calls", None) or []
                for tc in tcalls:
                    if isinstance(tc, dict):
                        nm = str(tc.get("name", "") or "tool")
                        args = tc.get("args", {})
                        sm = ""
                        if isinstance(args, dict) and args:
                            sm = str(list(args.items())[0])[:120]
                    else:
                        nm = str(getattr(tc, "name", "") or "tool")
                        sm = ""
                    self.add_tool_message(nm, sm)
                raw = str(m.content or "")
                thoughts, body = _split_thoughts_and_body(raw)
                for th in thoughts:
                    self.add_thought(th, skip_dedup=True)
                if tcalls:
                    if body.strip():
                        self._mount_main(
                            Static(Text(body.strip(), style=DIM), classes="stream-line"),
                        )
                elif body.strip():
                    self._msg_seq += 1
                    mid = str(self._msg_seq)
                    self._mount_main(
                        AssistantMessageBlock(
                            body.strip(),
                            self._footer_for_assistant(None),
                            mid,
                        ),
                    )
            elif isinstance(m, ToolMessage):
                body = str(m.content or "")[:240]
                nm = getattr(m, "name", None) or "tool"
                self.add_tool_result(str(nm), body)
        if not any(isinstance(m, HumanMessage) for m in msgs):
            self._add_welcome()
        self._refresh_context_meter()

    def add_assistant_message(self, text: str, usage: Optional[Dict[str, Any]] = None) -> None:
        text = self._append_web_sources_to_reply(text)
        _, body = _split_thoughts_and_body(text)
        if usage:
            inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            if inp or out:
                self._lifetime_prompt += max(0, inp)
                self._lifetime_completion += max(0, out)
        footer = self._footer_for_assistant(usage)
        if not (body or "").strip():
            self._mount_file_changes_table()
            self._mount_sources_widget()
            self.reset_round_file_metrics()
            self._refresh_context_meter()
            return
        self._msg_seq += 1
        mid = str(self._msg_seq)
        block = AssistantMessageBlock(body, footer, mid)
        self._mount_main(block)
        # File-changes summary and sources are placed AFTER the final
        # assistant reply, so the user reads the answer first and sees
        # the follow-up recap cards below. This works in every mode.
        self._mount_file_changes_table()
        self._mount_sources_widget()
        self.reset_round_file_metrics()
        self._refresh_context_meter()

    def add_tool_message(self, tool_name: str, summary: str = "") -> None:
        if self._is_duplicate_render(f"tool:{tool_name}:{summary[:80]}"):
            return
        colors = self._ui_colors()
        msg = Text()
        msg.append("▸ ", style=colors["accent"])
        msg.append(tool_name, style=f"bold {colors['accent']}")
        if summary:
            msg.append(f"  {summary[:180]}", style=colors["fg2"])
        self._mount_main(Static(msg, classes="stream-line"))

    def add_tool_result(self, tool_name: str, summary: str = "") -> None:
        if self._is_duplicate_render(f"tool_result:{tool_name}:{summary[:80]}"):
            return
        msg = Text()
        msg.append("  ← ", style=DIM)
        msg.append(tool_name, style=DIM)
        if summary:
            msg.append(f"  {summary[:180]}", style=DIM)
        self._mount_main(Static(msg, classes="stream-line"))

    def add_tool_card(self, tool_name: str, result: Any) -> None:
        """Mount a pretty, collapsible card for read-only / action tools.

        Called from :meth:`Interface.tui_bridge.TUIBridge.on_tool_result`
        for every tool whose name is in ``tool_card.PRETTY_TOOL_NAMES``.
        This gives ``read_file`` / ``list_files`` / ``run_command`` the
        same level of visual affordance as ``write_file`` (which uses
        :class:`~Interface.panels.diff_block.CodeDiffBlock`).
        """
        if ToolCardBlock is None:
            return self.add_tool_result(tool_name, str(result)[:120])
        dedup_key = f"toolcard:{tool_name}:{str(result)[:80]}"
        if self._is_duplicate_render(dedup_key):
            return
        try:
            self._mount_main(ToolCardBlock(tool_name, result))
        except Exception:
            self.add_tool_result(tool_name, str(result)[:120])

    def add_thought(self, text: str, *, skip_dedup: bool = False) -> None:
        if not skip_dedup and self._is_duplicate_render(f"thought:{(text or '')[:120]}"):
            return
        for line in (text or "")[:2000].split("\n")[:40]:
            self._mount_main(Static(Text(f"· {line}", style=f"italic {DIM}"), classes="stream-line"))

    def add_error(self, text: str) -> None:
        if self._is_duplicate_render(f"error:{text[:120]}"):
            return
        self._mount_main(Static(Text(f"✗ {text}", style=f"bold {RED}"), classes="stream-line"))

    def add_info(self, text: str) -> None:
        if self._is_duplicate_render(f"info:{text[:120]}"):
            return
        self._mount_main(Static(Text(text, style=self._ui_colors()["fg2"]), classes="stream-line"))

    def register_context_hint(self, path: Path) -> None:
        try:
            p = str(path.resolve())
        except Exception:
            p = str(path)
        if p not in self._context_hints:
            self._context_hints.append(p)
        self._rebuild_attachment_strip()

    def remove_context_index(self, index: int) -> None:
        if 0 <= index < len(self._context_hints):
            self._context_hints.pop(index)
            self._rebuild_attachment_strip()

    def remove_pending_image_index(self, index: int) -> None:
        if 0 <= index < len(self._pending_images):
            self._pending_images.pop(index)
            self._rebuild_attachment_strip()

    def get_context_hints(self) -> List[str]:
        return list(self._context_hints)

    def add_success(self, text: str) -> None:
        self._mount_main(Static(Text(f"✓ {text}", style=f"bold {GREEN}"), classes="stream-line"))

    def add_warning(self, text: str) -> None:
        accent = self._ui_colors()["accent"]
        self._mount_main(Static(Text(f"⚠ {text}", style=f"bold {accent}"), classes="stream-line"))

    def add_separator(self, label: str = "") -> None:
        colors = self._ui_colors()
        sep = Text()
        sep.append("─" * 12, style=colors["fg2"])
        if label:
            sep.append(f" {label} ", style=colors["fg2"])
            sep.append("─" * 12, style=colors["fg2"])
        self._mount_main(Static(sep, classes="stream-line"))

    def add_file_indicator(self, path: str) -> None:
        name = Path(path).name if path else "unknown"
        accent = self._ui_colors()["accent"]
        self._mount_main(Static(Text(f"📄 {name}", style=f"{accent}"), classes="stream-line"))

    # ─── Deep Solver checkpoints ────────────────────────────────────
    # The Deep mode drops a checkpoint card in the chat every few
    # tool-rounds (or when the model explicitly calls deep_checkpoint).
    # The card exposes two buttons; pressing either trims the history
    # back to that snapshot. "Continue" additionally plants a pseudo-
    # attachment chip so the user can seed a prompt from that point.
    def add_deep_checkpoint(self, cp_id: str, index: int, title: str,
                            summary: str = "", turn_index: int = 0) -> None:
        if DeepCheckpointBlock is None:
            self._mount_main(Static(
                Text(f"◆ Чекпоинт #{index}: {title}",
                     style=f"bold {self._ui_colors()['accent']}"),
                classes="stream-line",
            ))
            return
        block = DeepCheckpointBlock(
            checkpoint_id=cp_id, index=index, title=title,
            summary=summary, turn_index=turn_index,
        )
        self._mount_main(block)

    def set_deep_status(self, *, running: bool, elapsed: str = "",
                        checkpoints: int = 0, model: str = "") -> None:
        """Show / hide the status bar above the input while a Deep run
        is alive. Called from :class:`Interface.tui_bridge.TUIBridge`
        every few seconds so the elapsed-time badge stays fresh without
        spamming the chat stream.
        """
        try:
            bar = self.query_one("#deep-status-bar", Static)
        except Exception:
            return
        if not running:
            bar.remove_class("-active")
            bar.update("")
            return
        accent = self._ui_colors().get("accent", "#8B5CF6")
        label = Text()
        label.append("◆ ", style=accent)
        label.append("Deep Solver  ·  ", style=f"bold {accent}")
        label.append(f"⏱ {elapsed or '0с'}", style="#E5E7EB")
        if checkpoints:
            label.append(f"  ·  чекпоинтов: {checkpoints}", style="#9CA3AF")
        if model:
            label.append(f"  ·  {model}", style="#6B7280")
        bar.update(label)
        bar.add_class("-active")

    def add_deep_context_chip(self, cp_id: str, label: str) -> None:
        """Planted by 'Continue from checkpoint' — shows up in the
        attachment strip as a neutral chip so the next user message is
        visibly anchored to that point in the project's timeline."""
        try:
            strip = self.query_one("#attachment-strip", Horizontal)
        except Exception:
            return
        btn_id = f"deepcp-chip-{cp_id}"
        try:
            self.query_one(f"#{btn_id}")
            return
        except Exception:
            pass
        try:
            strip.mount(Button(
                f"◆ {label}\n(нажмите — убрать)",
                id=btn_id,
                classes="attach-chip",
            ))
        except Exception:
            pass

    def add_code_block(self, code: str, language: str = "python", filepath: str = "") -> None:
        accent = self._ui_colors()["accent"]
        label = filepath if filepath else language
        lines = [Text(f"│ {line}", style="#D1D5DB") for line in code[:1500].split("\n")[:16]]
        self._mount_main(Static(Text(f"┌ {label}", style=accent), classes="stream-line"))
        for ln in lines:
            self._mount_main(Static(ln, classes="stream-line"))
        rest = len(code.split("\n")) - 16
        if rest > 0:
            self._mount_main(Static(Text(f"│ … +{rest} строк", style=DIM), classes="stream-line"))
        self._mount_main(Static(Text("└", style=accent), classes="stream-line"))

    def _refresh_context_meter(self) -> None:
        used = self._context_used
        total = self._context_total
        pct = round(100 * used / total) if total > 0 else 0
        pct = max(0, min(100, pct))
        bar_w = 16
        filled = round(bar_w * pct / 100)
        filled = max(0, min(bar_w, filled))
        bar = "[" + "=" * filled + "-" * (bar_w - filled) + "]"
        accent = self._ui_colors()["accent"]
        if pct < 50:
            pct_style = GREEN
        elif pct < 85:
            pct_style = accent
        else:
            pct_style = RED
        try:
            pv = self.query_one("#ctx-progress-visual", Static)
            pv.update(Text.assemble(
                (f"Окно {bar} ", ""),
                (f"{pct}%", f"bold {pct_style}"),
                (f"  ~{used:,}/{total:,} ток.", "dim"),
            ))
        except Exception:
            pass
        lt = self._lifetime_prompt + self._lifetime_completion
        try:
            sl = self.query_one("#ctx-session-line", Static)
            sl.update(Text.assemble(
                ("Σ ", "dim"),
                (f"↑{self._lifetime_prompt:,}", ""),
                (" ", ""),
                (f"↓{self._lifetime_completion:,}", ""),
                ("  ", "dim"),
                (f"(~{lt:,})", "dim"),
            ))
        except Exception:
            pass

    def update_context(self, used: int, total: int) -> None:
        self._context_used = used
        self._context_total = total if total > 0 else self._context_total
        self._refresh_context_meter()

    def update_model(self, model_id: str) -> None:
        self._current_model = model_id
        try:
            sel = self.query_one("#model-select", Select)
            sel.value = model_id
        except Exception:
            pass

    def show_stop_button(self) -> None:
        try:
            self.query_one("#stop-btn", Button).add_class("visible")
        except Exception:
            pass

    def hide_stop_button(self) -> None:
        try:
            self.query_one("#stop-btn", Button).remove_class("visible")
        except Exception:
            pass

    def start_creator_progress(self, task: str = "", total_workers: int = 0) -> None:
        """Mount the Creator Mode progress strip above the input area.

        Safe to call multiple times — the previous block is replaced.
        """
        if CreatorProgressBlock is None:
            return
        try:
            slot = self.query_one("#creator-progress-slot", Vertical)
        except Exception:
            return
        try:
            for child in list(slot.children):
                try:
                    child.remove()
                except Exception:
                    pass
            self._creator_progress = None
            try:
                slot.remove_class("hidden")
            except Exception:
                pass
            block = CreatorProgressBlock(task=task, total_workers=int(total_workers or 0))
            self._creator_progress = block
            slot.mount(block)
        except Exception:
            self._creator_progress = None

    def update_creator_progress(
        self,
        phase: str = "",
        percent: float = 0.0,
        completed: int = 0,
        total: int = 0,
    ) -> None:
        """Update the creator progress block with new phase / percent values."""
        block = self._creator_progress
        if block is None:
            return
        try:
            block.update_progress(
                phase=phase or None,
                percent=float(percent) if percent is not None else None,
                completed=int(completed) if completed is not None else None,
                total=int(total) if total is not None else None,
            )
        except Exception:
            pass

    def finish_creator_progress(self, summary: str = "") -> None:
        """Fill the strip to 100 % — the widget tears itself down when done."""
        block = self._creator_progress
        if block is None:
            return
        try:
            block.finish(summary=summary or "")
        except Exception:
            pass
        # Release our reference right away: the widget will self-remove once
        # its own animation catches up, and a new start_creator_progress call
        # will safely replace any lingering child in the slot.
        self._creator_progress = None

    def update_creator_worker(self, worker_id: str, tool_name: str = "",
                               action: str = "", thinking: str = "") -> None:
        if worker_id not in self._worker_logs:
            self._worker_logs[worker_id] = []
        entries = self._worker_logs[worker_id]
        parts: List[str] = []
        if tool_name:
            parts.append(f"### `{tool_name}`")
        if action:
            parts.append(action or "")
        if thinking:
            parts.append("\n" + (thinking or "").replace("\n", "\n"))
        block = "\n\n".join(p for p in parts if p).strip()
        if block:
            entries.append(block)
        if len(entries) > 200:
            self._worker_logs[worker_id] = entries[-120:]

        if self._view_worker != worker_id:
            return
        wlog = self._worker_visible_log()
        if block:
            wlog.write(Markdown(block))

    def _is_duplicate_render(self, key: str, window_sec: float = 1.2) -> bool:
        now = time.time()
        if key == self._last_render_key and (now - self._last_render_ts) < window_sec:
            return True
        self._last_render_key = key
        self._last_render_ts = now
        return False

    def _submit_chat_text(self) -> None:
        if self._view_worker:
            return
        try:
            ta = self.query_one("#chat-input", TextArea)
        except Exception:
            return
        text = (ta.text or "").strip()
        ta.text = ""
        if not text:
            return
        imgs = list(self._pending_images)
        self._pending_images.clear()
        self._rebuild_attachment_strip()
        self.post_message(ChatSubmitted(text, imgs, bubble_text=text))

    def action_submit_chat(self) -> None:
        self._submit_chat_text()

    @on(Button.Pressed, "#attach-file-btn")
    def on_attach_file(self) -> None:
        try:
            fe = self.app.query_one("#file-explorer")
            start = fe.project_root
        except Exception:
            start = Path.cwd()

        def _picked(p: Optional[Path]) -> None:
            if not p or not p.is_file():
                return
            suf = p.suffix.lower()
            if suf in _CHAT_IMAGE_EXT:
                rp = p.resolve()
                if rp not in self._pending_images:
                    self._pending_images.append(rp)
                self.notify(f"Картинка: {p.name}")
            else:
                self.register_context_hint(p)
                self.notify(f"В контекст: {p.name}")
            self._rebuild_attachment_strip()

        self.app.push_screen(ChatFilePickerScreen(start), _picked)

    @on(Button.Pressed, "#attachment-strip Button")
    def on_attachment_chip(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("ctx_"):
            try:
                idx = int(bid.rsplit("_", 1)[-1])
                self.remove_context_index(idx)
            except ValueError:
                pass
        elif bid.startswith("img_"):
            try:
                idx = int(bid.rsplit("_", 1)[-1])
                self.remove_pending_image_index(idx)
            except ValueError:
                pass
        elif bid.startswith("deepcp-chip-"):
            try:
                event.button.remove()
            except Exception:
                pass

    @on(Button.Pressed, ".deepcp-rollback")
    def on_deep_checkpoint_rollback(self, event: Button.Pressed) -> None:
        """Rollback: restore snapshot, trim chat, discard checkpoint."""
        event.stop()
        bid = event.button.id or ""
        cp_id = bid[len("deepcp-rollback-"):] if bid.startswith("deepcp-rollback-") else ""
        if not cp_id:
            return
        self.post_message(DeepCheckpointAction(cp_id=cp_id, action="rollback"))
        self._mark_deep_checkpoint_done(cp_id, note="Откат запущен")

    @on(Button.Pressed, ".deepcp-continue")
    def on_deep_checkpoint_continue(self, event: Button.Pressed) -> None:
        """Continue: same rollback + plant a context chip for the next prompt."""
        event.stop()
        bid = event.button.id or ""
        cp_id = bid[len("deepcp-continue-"):] if bid.startswith("deepcp-continue-") else ""
        if not cp_id:
            return
        self.post_message(DeepCheckpointAction(cp_id=cp_id, action="continue"))
        self._mark_deep_checkpoint_done(cp_id, note="Продолжаем с этого чекпоинта")

    def _mark_deep_checkpoint_done(self, cp_id: str, note: str = "") -> None:
        if DeepCheckpointBlock is None:
            return
        try:
            for block in self.query(DeepCheckpointBlock):
                if getattr(block, "checkpoint_id", "") == cp_id:
                    block.mark_done(note)
                    break
        except Exception:
            pass

    # ─── Download progress widget ────────────────────
    #
    # ``TUIBridge.on_download_progress`` drops ticks here. We lazily
    # create a :class:`DownloadProgressBlock` keyed by ``download_id``
    # and update it in place until the final ``done=True`` tick arrives.

    def update_download_progress(self, *, download_id: str, url: str,
                                 received_bytes: int, total_bytes: int,
                                 elapsed: float, done: bool,
                                 error: str = "") -> None:
        if DownloadProgressBlock is None:
            return
        block: Optional[DownloadProgressBlock] = None
        try:
            for b in self.query(DownloadProgressBlock):
                if getattr(b, "download_id", "") == download_id:
                    block = b
                    break
        except Exception:
            block = None
        if block is None:
            try:
                block = DownloadProgressBlock(download_id=download_id, url=url)
                self._mount_main(block)
            except Exception:
                return
        try:
            block.update_progress(
                received=received_bytes, total=total_bytes,
                elapsed=elapsed, done=done, error=error,
            )
        except Exception:
            pass

    @on(Button.Pressed, ".dl-cancel")
    def on_download_cancel(self, event: Button.Pressed) -> None:
        """Cancel button on a ``DownloadProgressBlock`` — sets the
        cancellation flag the streaming download loop polls."""
        event.stop()
        bid = event.button.id or ""
        if not bid.startswith("dl-cancel-"):
            return
        download_id = bid[len("dl-cancel-"):]
        try:
            from Agent.tools.download_tool import cancel_download
            cancel_download(download_id)
        except Exception:
            pass
        try:
            event.button.label = "Отмена…"
            event.button.disabled = True
        except Exception:
            pass

    @on(Button.Pressed, "#send-btn")
    def on_send_click(self) -> None:
        self._submit_chat_text()

    @on(Button.Pressed, "#stop-btn")
    def on_stop_click(self) -> None:
        self.post_message(StopRequested())

    def _broadcast_accent_refresh(self) -> None:
        """Walk the widget tree and call refresh_accent() on every widget that supports it.

        This lets custom widgets (UserMessageBlock, CodeDiffBlock, CreatorProgressBlock,
        and re-renderable Label titles) re-render their inline Rich text with the
        freshly-picked accent colour — no app restart required.
        """
        try:
            root = self.app
        except Exception:
            root = self
        try:
            widgets = list(root.query("*"))
        except Exception:
            widgets = []
        for w in widgets:
            fn = getattr(w, "refresh_accent", None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
        # Accent-styled Label/Static built via _section_title/_settings_title/_settings_row
        # carry a dedicated class so we can re-colour them in-place.
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import get_theme
            prefs = load_prefs()
            theme = get_theme(str(prefs.get("theme", "Purple Dark")))
            accent = str(prefs.get("accent_color") or theme.get("accent") or PURPLE)
        except Exception:
            accent = self._accent()
        for cls in (
            "settings-section-title",
            "settings-card-title",
            "settings-row-label",
            "param-cell-label",
        ):
            try:
                for lbl in root.query(f".{cls}"):
                    try:
                        txt = lbl.renderable
                        raw = txt.plain if hasattr(txt, "plain") else str(txt)
                        lbl.update(Text(raw, style=f"bold {accent}"))
                    except Exception:
                        try:
                            lbl.styles.color = accent
                        except Exception:
                            pass
            except Exception:
                pass

    def on_apply_accent(self) -> None:
        color = (self.app.query_one("#sp-accent", Input).value or "").strip()
        if not color.startswith("#"):
            self.notify("Цвет должен начинаться с #", severity="warning")
            return
        try:
            from Interface.ui_prefs import save_prefs, load_prefs
            from Interface.themes import apply_theme
            save_prefs(accent_color=color)
            apply_theme(self.app, str(load_prefs().get("theme", "Purple Dark")))
            self._broadcast_accent_refresh()
            self.notify("Цвет обновлён")
        except Exception as e:
            self.notify(f"Accent error: {e}", severity="error")

    def on_open_palette(self) -> None:
        def _picked(color: Optional[str]) -> None:
            if not color:
                return
            try:
                inp = self.app.query_one("#sp-accent", Input)
                inp.value = color
            except Exception:
                pass
            try:
                from Interface.ui_prefs import save_prefs, load_prefs
                from Interface.themes import apply_theme
                save_prefs(accent_color=color)
                apply_theme(self.app, str(load_prefs().get("theme", "Purple Dark")))
                self._broadcast_accent_refresh()
                self.notify("Цвет обновлён")
            except Exception:
                pass

        self.app.push_screen(_AccentPaletteDialog(_ACCENT_COLORS, _picked))

    def on_sp_theme(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        try:
            from Interface.ui_prefs import save_prefs
            from Interface.themes import apply_theme
            theme_name = str(event.value)
            save_prefs(theme=theme_name)
            apply_theme(self.app, theme_name)
            self._broadcast_accent_refresh()
        except Exception as e:
            self.notify(f"Theme error: {e}", severity="error")

    def on_sp_density(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        density = str(event.value)
        for d in ("compact", "normal", "spacious"):
            self.app.remove_class(f"density-{d}")
        self.app.add_class(f"density-{density}")
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(density=density)
        except Exception:
            pass

    def on_sp_syntax(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        key = str(event.value)
        theme_actual = MARKDOWN_SYNTAX_THEME_MAP.get(key, "monokai")
        try:
            from Interface.themes import ensure_custom_textarea_themes
            from Interface.ui_prefs import save_prefs
            for ta in self.app.query(TextArea):
                ensure_custom_textarea_themes(ta)
                ta.theme = theme_actual
            save_prefs(syntax_theme=key)
        except Exception:
            pass

    def on_sa_profile(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        os.environ["TCA_PROFILE"] = str(event.value)
        self.notify(f"Профиль агента: {event.value}")

    def on_sa_browser(self, event: Checkbox.Changed) -> None:
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(browser_tools_enabled=bool(event.value))
            self.notify("browser tools: " + ("ON" if event.value else "OFF"))
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    def on_sa_playwright(self, event: Checkbox.Changed) -> None:
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(playwright_python_enabled=bool(event.value))
            self.notify("playwright tools: " + ("ON" if event.value else "OFF"))
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    def on_sa_custom_tools(self, event: Checkbox.Changed) -> None:
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(custom_tools_enabled=bool(event.value))
            self.notify("кастом-тулы: " + ("ON" if event.value else "OFF"))
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    def on_sa_orch_mode(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(orchestration_mode=str(event.value))
            self.notify(f"Оркестрация: {event.value}")
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    def on_sa_research_deep_fetch(self, event: Checkbox.Changed) -> None:
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(research_deep_fetch=bool(event.value))
            self.notify("deep fetch: " + ("ON" if event.value else "OFF"))
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    def on_sa_apply(self) -> None:
        """Persist orchestration / research numeric knobs entered by the user."""
        def _int(wid: str, default: int) -> int:
            try:
                raw = (self.app.query_one(wid, Input).value or "").strip()
                return max(1, int(raw))
            except Exception:
                return default
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(
                orchestration_max_workers=_int("#sa-orch-max-workers", 4),
                research_max_sources=_int("#sa-research-max-sources", 6),
                research_max_rounds=_int("#sa-research-max-rounds", 3),
            )
            try:
                self.app.query_one("#sa-status", Static).update(
                    Text("Сохранено. Применится к следующему запуску.", style=GREEN),
                )
            except Exception:
                pass
            self.notify("Настройки агента сохранены")
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    def on_sor_check_balance(self) -> None:
        display = self.app.query_one("#sor-balance-display", Static)

        def _resolve_key() -> str:
            raw = (self.app.query_one("#sor-api-key", Input).value or "").strip()
            if raw and not raw.endswith("…"):
                return raw
            return (os.environ.get("OPENROUTER_API_KEY") or "").strip()

        display.update("Запрос к OpenRouter…")

        def _work() -> None:
            key = _resolve_key()
            if not key:
                self.app.call_from_thread(
                    display.update,
                    "Нет ключа: введите API key в поле выше или сохраните его кнопкой «Сохранить API key».",
                )
                return
            try:
                from Agent.llm_provider import fetch_openrouter_credits, format_credits_info
                from Interface.panels.usage_calendar import record_cumulative_usage, UsageCalendar

                creds = fetch_openrouter_credits(key)
                if creds:
                    self.app.call_from_thread(display.update, format_credits_info(creds))
                    try:
                        total_usd = float(creds.get("usage", 0.0) or 0.0)
                        record_cumulative_usage(total_usd)
                    except Exception:
                        pass

                    def _refresh_cal() -> None:
                        try:
                            cal = self.app.query_one("#sor-usage-calendar", UsageCalendar)
                            cal.reload()
                        except Exception:
                            pass

                    self.app.call_from_thread(_refresh_cal)
                else:
                    self.app.call_from_thread(
                        display.update,
                        "Не удалось получить данные. Проверьте ключ и сеть.",
                    )
            except Exception as e:
                self.app.call_from_thread(display.update, f"Ошибка: {e}")

        threading.Thread(target=_work, daemon=True).start()

    def on_sor_save_key(self) -> None:
        key = (self.app.query_one("#sor-api-key", Input).value or "").strip()
        if not key or key.endswith("…"):
            self.notify("Введите новый OpenRouter API key", severity="warning")
            return
        os.environ["OPENROUTER_API_KEY"] = key
        try:
            self._update_env_file("OPENROUTER_API_KEY", key)
            self.notify("OpenRouter API key сохранён")
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    def on_sor_add_model(self) -> None:
        model_id = (self.app.query_one("#sor-model-id", Input).value or "").strip()
        custom_name = (self.app.query_one("#sor-model-name", Input).value or "").strip()
        if not model_id:
            self.notify("Укажите model id", severity="warning")
            return
        status = self.app.query_one("#sor-status", Static)
        status.update("Загружаю метаданные OpenRouter…")

        def _work() -> None:
            try:
                from Agent.llm_provider import fetch_openrouter_model_metadata
                from Interface.ui_prefs import load_prefs, save_prefs

                row = fetch_openrouter_model_metadata(model_id, os.environ.get("OPENROUTER_API_KEY", ""))
                name = custom_name or str((row or {}).get("name") or model_id)
                ctx = int((row or {}).get("context_length") or 128_000)
                tier = "custom"
                prefs = load_prefs()
                cur = [m for m in (prefs.get("openrouter_custom_models") or []) if isinstance(m, dict)]
                cur = [m for m in cur if str(m.get("id") or "") != model_id]
                cur.append({"id": model_id, "name": name, "ctx": ctx, "tier": tier})
                save_prefs(openrouter_custom_models=cur)
                self.app.call_from_thread(
                    self.add_external_model,
                    model_id,
                    name,
                    ctx,
                    tier,
                    "openrouter",
                    True,
                )
                self.app.call_from_thread(status.update, f"Добавлено: {name} ({ctx} ctx)")
                self.app.call_from_thread(self._refresh_openrouter_list_view)
                self.app.call_from_thread(self._update_custom_models_line)
            except Exception as e:
                self.app.call_from_thread(status.update, f"Ошибка: {e}")

        threading.Thread(target=_work, daemon=True).start()

    def on_sol_save_conn(self) -> None:
        base = (self.app.query_one("#sol-base-url", Input).value or "").strip()
        api = (self.app.query_one("#sol-api-key", Input).value or "").strip()
        if not base:
            self.notify("Введите base URL", severity="warning")
            return
        os.environ["OLLAMA_BASE_URL"] = base
        os.environ["OLLAMA_API_KEY"] = api
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(ollama_base_url=base, ollama_api_key=api)
            self._update_env_file("OLLAMA_BASE_URL", base)
            self._update_env_file("OLLAMA_API_KEY", api)
            self.notify("Настройки Ollama сохранены")
        except Exception as e:
            self.notify(f"Ошибка: {e}", severity="error")

    def _read_ollama_params_form(self) -> Dict[str, Any]:
        def _f(id_: str, default: float) -> float:
            try:
                return float((self.app.query_one(id_, Input).value or "").strip())
            except Exception:
                return float(default)

        def _i(id_: str, default: int) -> int:
            try:
                return int((self.app.query_one(id_, Input).value or "").strip())
            except Exception:
                return int(default)

        stop_raw = ""
        try:
            stop_raw = (self.app.query_one("#sol-param-stop", Input).value or "").strip()
        except Exception:
            stop_raw = ""
        return {
            "temperature": _f("#sol-param-temperature", 0.2),
            "top_p": _f("#sol-param-top-p", 0.9),
            "top_k": _i("#sol-param-top-k", 40),
            "repeat_penalty": _f("#sol-param-repeat-penalty", 1.1),
            "num_ctx": _i("#sol-param-num-ctx", 32768),
            "num_predict": _i("#sol-param-num-predict", 8192),
            "stop": stop_raw,
        }

    def on_sol_preset_changed(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        try:
            from Interface.ui_prefs import load_prefs
            presets = load_prefs().get("ollama_presets") or {}
            pv = presets.get(str(event.value), {}) if isinstance(presets, dict) else {}
            if not isinstance(pv, dict):
                return
            self.app.query_one("#sol-param-temperature", Input).value = str(pv.get("temperature", 0.2))
            self.app.query_one("#sol-param-top-p", Input).value = str(pv.get("top_p", 0.9))
            self.app.query_one("#sol-param-top-k", Input).value = str(pv.get("top_k", 40))
            self.app.query_one("#sol-param-repeat-penalty", Input).value = str(pv.get("repeat_penalty", 1.1))
            self.app.query_one("#sol-param-num-ctx", Input).value = str(pv.get("num_ctx", 32768))
            self.app.query_one("#sol-param-num-predict", Input).value = str(pv.get("num_predict", 8192))
            self.app.query_one("#sol-param-stop", Input).value = str(pv.get("stop", ""))
        except Exception:
            pass

    def on_sol_save_preset(self) -> None:
        try:
            from Interface.ui_prefs import load_prefs, save_prefs
            preset_name = str(self.app.query_one("#sol-preset-select", Select).value or "default").strip() or "default"
            prefs = load_prefs()
            presets = prefs.get("ollama_presets") if isinstance(prefs.get("ollama_presets"), dict) else {}
            presets[preset_name] = self._read_ollama_params_form()
            save_prefs(ollama_presets=presets)
            self.notify(f"Пресет сохранён: {preset_name}")
        except Exception as e:
            self.notify(f"Preset error: {e}", severity="error")

    def on_sol_apply_model_settings(self) -> None:
        try:
            model_name = str(self.app.query_one("#sol-model-select", Select).value or "").strip()
            if not model_name:
                self.notify("Сначала выберите модель Ollama", severity="warning")
                return
            from Interface.ui_prefs import load_prefs, save_prefs
            prefs = load_prefs()
            mapping = prefs.get("ollama_model_settings") if isinstance(prefs.get("ollama_model_settings"), dict) else {}
            mapping[model_name] = {
                "preset": str(self.app.query_one("#sol-preset-select", Select).value or "default"),
                **self._read_ollama_params_form(),
            }
            save_prefs(ollama_model_settings=mapping)
            self.notify(f"Настройки применены к {model_name}")
        except Exception as e:
            self.notify(f"Model settings error: {e}", severity="error")

    def on_sol_refresh(self) -> None:
        status = self.app.query_one("#sol-status", Static)
        status.update("Запрашиваю список Ollama моделей…")
        base = (self.app.query_one("#sol-base-url", Input).value or "").strip()
        api = (self.app.query_one("#sol-api-key", Input).value or "").strip()

        def _work() -> None:
            try:
                from Agent.llm_provider import fetch_ollama_models
                rows = fetch_ollama_models(base_url=base, api_key=api)
                opts = [(f"{r.get('name')} (ctx {int(r.get('ctx') or 0):,})", str(r.get("name"))) for r in rows]
                if not opts:
                    opts = [("Модели не найдены", "")]

                def _apply() -> None:
                    sel = self.app.query_one("#sol-model-select", Select)
                    sel.set_options(opts)
                    if opts:
                        sel.value = opts[0][1]
                    status.update(f"Найдено моделей: {len(rows)}")

                self.app.call_from_thread(_apply)
            except Exception as e:
                self.app.call_from_thread(status.update, f"Ошибка: {e}")

        threading.Thread(target=_work, daemon=True).start()

    def on_sol_model_select(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        model_name = str(event.value)
        try:
            from Interface.ui_prefs import load_prefs
            prefs = load_prefs()
            settings = prefs.get("ollama_model_settings") if isinstance(prefs.get("ollama_model_settings"), dict) else {}
            ms = settings.get(model_name) if isinstance(settings.get(model_name), dict) else None
            if not ms:
                return
            preset = str(ms.get("preset") or "default")
            try:
                self.app.query_one("#sol-preset-select", Select).value = preset
            except Exception:
                pass
            self.app.query_one("#sol-param-temperature", Input).value = str(ms.get("temperature", 0.2))
            self.app.query_one("#sol-param-top-p", Input).value = str(ms.get("top_p", 0.9))
            self.app.query_one("#sol-param-top-k", Input).value = str(ms.get("top_k", 40))
            self.app.query_one("#sol-param-repeat-penalty", Input).value = str(ms.get("repeat_penalty", 1.1))
            self.app.query_one("#sol-param-num-ctx", Input).value = str(ms.get("num_ctx", 32768))
            self.app.query_one("#sol-param-num-predict", Input).value = str(ms.get("num_predict", 8192))
            self.app.query_one("#sol-param-stop", Input).value = str(ms.get("stop", ""))
        except Exception:
            pass

    def on_sol_add(self) -> None:
        try:
            model_name = str(self.app.query_one("#sol-model-select", Select).value or "").strip()
        except Exception:
            model_name = ""
        if not model_name:
            self.notify("Сначала обновите и выберите модель", severity="warning")
            return
        from Interface.ui_prefs import load_prefs, save_prefs

        prefs = load_prefs()
        params = self._read_ollama_params_form()
        selected_preset = str(self.app.query_one("#sol-preset-select", Select).value or "default")
        cur = [m for m in (prefs.get("ollama_custom_models") or []) if isinstance(m, dict)]
        cur = [m for m in cur if str(m.get("name") or "") != model_name]
        model_ctx = int(params.get("num_ctx") or 32768)
        cur.append({"name": model_name, "label": f"Ollama · {model_name}", "ctx": model_ctx})
        mset = prefs.get("ollama_model_settings") if isinstance(prefs.get("ollama_model_settings"), dict) else {}
        mset[model_name] = {"preset": selected_preset, **params}
        save_prefs(ollama_custom_models=cur, ollama_model_settings=mset)
        self.add_external_model(
            f"ollama/{model_name}",
            name=f"Ollama · {model_name}",
            ctx=model_ctx,
            tier="local",
            source="ollama",
            activate=True,
        )
        self._refresh_ollama_list_view()
        self._update_custom_models_line()

    @on(Select.Changed, "#mode-select")
    def on_mode_change(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        mode = str(event.value)
        self._current_mode = mode
        self.post_message(ModeToggled(mode))
        self.notify(f"Режим: {mode}")

    @on(Select.Changed, "#model-select")
    def on_model_change(self, event: Select.Changed) -> None:
        if event.value and event.value != Select.BLANK:
            self.post_message(ModelChanged(str(event.value)))

    def add_external_model(
        self,
        model_id: str,
        name: str = "",
        ctx: int = 0,
        tier: str = "custom",
        source: str = "custom",
        activate: bool = True,
    ) -> None:
        if not model_id:
            return
        if any(str(m.get("id") or "") == model_id for m in self._models):
            if activate:
                try:
                    self.query_one("#model-select", Select).value = model_id
                    self.post_message(ModelChanged(model_id))
                except Exception:
                    pass
            return
        short = name or (model_id.split("/")[-1] if "/" in model_id else model_id)
        if len(short) > 25:
            short = short[:22] + "…"
        self._models.append(
            {"name": short, "id": model_id, "ctx": int(ctx or 0), "tier": tier, "source": source}
        )
        model_options = []
        for m in self._models:
            name = m.get("name", m.get("id", "?"))
            mid = m.get("id", name)
            sn = name.split("/")[-1] if "/" in name else name
            if len(sn) > 25:
                sn = sn[:22] + "…"
            model_options.append((sn, mid))
        try:
            sel = self.query_one("#model-select", Select)
            sel.set_options(model_options)
            if activate:
                sel.value = model_id
                self.post_message(ModelChanged(model_id))
        except Exception:
            pass


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
