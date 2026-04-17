"""AI Chat — центр: поток сообщений (Markdown), вложения над вводом, метрики раунда."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.markdown import Markdown
from rich.text import Text

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DirectoryTree, Input, Label, RichLog, Select, Static, TextArea,
)

try:
    from textual.widgets import Markdown as MarkdownWidget
except ImportError:  # pragma: no cover
    MarkdownWidget = None  # type: ignore[misc, assignment]


class ChatSubmitted(Message):
    def __init__(self, text: str, image_paths: Optional[List[Path]] = None) -> None:
        super().__init__()
        self.text = text
        self.image_paths = list(image_paths or [])


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


class ChatFilePickerScreen(ModalScreen[Optional[Path]]):
    """Модальное дерево файлов проекта — выбор файла для контекста или изображения."""

    DEFAULT_CSS = """
    ChatFilePickerScreen { align: center middle; }
    #chatfp {
        width: 88%;
        height: 86%;
        background: #151520;
        border: round #8B5CF6;
        padding: 1;
    }
    #chatfp-title { height: 1; text-style: bold; margin: 0 0 1 0; }
    #chatfp-nav { height: 3; layout: horizontal; margin: 0 0 1 0; }
    #chatfp-nav Button { min-width: 10; margin: 0 1 0 0; }
    #chatfp-path { width: 1fr; }
    #chatfp-tree { height: 1fr; }
    #chatfp-actions { height: 3; layout: horizontal; margin: 1 0 0 0; }
    #chatfp-actions Button { min-width: 18; margin: 0 1 0 0; }
    """

    def __init__(self, start_dir: Path) -> None:
        super().__init__()
        self._start_dir = start_dir.expanduser().resolve()
        self._selected_dir = self._start_dir
        self._picked_file: Optional[Path] = None
        self._root = Path("/")

    def compose(self) -> ComposeResult:
        with Vertical(id="chatfp"):
            yield Label("Выберите файл (изображения — во вложения, остальное — в контекст)", id="chatfp-title")
            with Horizontal(id="chatfp-nav"):
                yield Button("Корень", id="chatfp-root")
                yield Button("Домой", id="chatfp-home")
                yield Button("Вверх", id="chatfp-up")
                yield Button("Проект", id="chatfp-proj")
                yield Input(str(self._start_dir), id="chatfp-path")
            yield DirectoryTree(str(self._root), id="chatfp-tree")
            with Horizontal(id="chatfp-actions"):
                yield Button("Выбрать файл", id="chatfp-open")
                yield Button("Отмена", id="chatfp-cancel")

    def on_mount(self) -> None:
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

MODES = ["Normal", "Creator", "Agent", "Research"]
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

_WRITE_TOOLS = frozenset({
    "edit_file", "write_file", "replace_file_lines", "insert_file_lines",
    "create_code_file", "append_code_snippet",
})

_WEB_TOOLS = frozenset({"web_search", "web_fetch", "web_search_and_read"})

_CHAT_IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})


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
    """

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static(Text("Вы", style=f"bold {PURPLE_LIGHT}"))
        yield Static(Text(self._text, style="#E5E7EB"))


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
    .chat-input-hint {
        height: auto;
        min-height: 1;
        color: #6B7280;
        margin: 0 0 0 0;
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
    .stream-line {
        height: auto;
        margin: 0 0 0 0;
        color: #9CA3AF;
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
        self._round_web_sources: List[Dict[str, str]] = []
        self._round_web_seen: set[str] = set()
        self._chip_epoch = 0
        self._lifetime_prompt = 0
        self._lifetime_completion = 0

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
            ta = self.query_one("#chat-input", TextArea)
            ensure_custom_textarea_themes(ta)
            ta.theme = SYNTAX_THEME_MAP.get(
                str(load_prefs().get("syntax_theme", "monokai")), "monokai",
            )
        except Exception:
            pass
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
        area.mount(Label(
            "Ctrl+Enter — отправить  ·  Enter — новая строка  ·  до 12 строк с прокруткой",
            id="chat-input-hint",
            classes="chat-input-hint",
        ))

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
            hint = self.query_one("#chat-input-hint", Label)
            for bid in ("#model-select", "#mode-select", "#send-btn", "#attach-file-btn"):
                try:
                    self.query_one(bid).disabled = bool(wid)
                except Exception:
                    pass
            try:
                self.query_one("#ctx-meter-row", Horizontal).disabled = bool(wid)
            except Exception:
                pass
            if wid:
                ta.disabled = True
                hint.update("Переключитесь на «Общий чат» слева внизу, чтобы писать сообщения.")
            else:
                ta.disabled = False
                hint.update(
                    "Ctrl+Enter — отправить  ·  Enter — новая строка  ·  до 12 строк с прокруткой",
                )
        except Exception:
            pass

        if not wid:
            stream.display = True
            wlog.display = False
            label.update("Чат проекта")
        else:
            stream.display = False
            wlog.display = True
            label.update(Text(f"Воркер: {wid}", style=f"bold {YELLOW}"))
            wlog.clear()
            wlog.write(Markdown(
                f"> Лог воркера **`{wid}`**. Чтобы писать в общий чат, выберите узел **«Общий чат»** слева внизу.\n",
            ))
            for line in self._worker_logs.get(wid, [])[-200:]:
                wlog.write(Markdown(line))

    def reset_round_file_metrics(self) -> None:
        self._round_file_deltas.clear()

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
        if not self._round_web_sources:
            return text or ""
        lines = ["\n\n---\n### Источники\n"]
        for s in self._round_web_sources:
            u = s["url"]
            t = (s.get("title") or u).replace("\n", " ").strip()
            t = t.replace("[", "(").replace("]", ")")
            if len(t) > 160:
                t = t[:157] + "…"
            label = t if t else u
            lines.append(f"- [{label}]({u})\n")
        self._round_web_sources.clear()
        self._round_web_seen.clear()
        return (text or "").rstrip() + "".join(lines)

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

    def _footer_for_assistant(self, usage: Optional[Dict[str, Any]]) -> str:
        parts: List[str] = []
        if self._round_file_deltas:
            bits = []
            for p, d in sorted(self._round_file_deltas.items(), key=lambda x: x[0])[:12]:
                name = Path(p).name
                bits.append(f"{name} ({d:+d} стр.)" if d else f"{name} (0)")
            if len(self._round_file_deltas) > 12:
                bits.append("…")
            parts.append("Файлы: " + ", ".join(bits))
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

    def add_user_message(self, text: str) -> None:
        self.reset_round_file_metrics()
        self.reset_round_web_sources()
        self._mount_main(UserMessageBlock(text))

    def add_assistant_message(self, text: str, usage: Optional[Dict[str, Any]] = None) -> None:
        self._msg_seq += 1
        mid = str(self._msg_seq)
        text = self._append_web_sources_to_reply(text)
        if usage:
            inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            if inp or out:
                self._lifetime_prompt += max(0, inp)
                self._lifetime_completion += max(0, out)
        footer = self._footer_for_assistant(usage)
        block = AssistantMessageBlock(text, footer, mid)
        self._mount_main(block)
        self.reset_round_file_metrics()
        self._refresh_context_meter()

    def add_tool_message(self, tool_name: str, summary: str = "") -> None:
        if self._is_duplicate_render(f"tool:{tool_name}:{summary[:80]}"):
            return
        colors = self._ui_colors()
        msg = Text()
        msg.append("▸ ", style=colors["accent"])
        msg.append(tool_name, style=f"bold {CYAN}")
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

    def add_thought(self, text: str) -> None:
        if self._is_duplicate_render(f"thought:{(text or '')[:120]}"):
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
        self._mount_main(Static(Text(f"⚠ {text}", style=f"bold {YELLOW}"), classes="stream-line"))

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
        self._mount_main(Static(Text(f"📄 {name}", style=f"{BLUE}"), classes="stream-line"))

    def add_code_block(self, code: str, language: str = "python", filepath: str = "") -> None:
        label = filepath if filepath else language
        lines = [Text(f"│ {line}", style="#D1D5DB") for line in code[:1500].split("\n")[:16]]
        self._mount_main(Static(Text(f"┌ {label}", style=CYAN), classes="stream-line"))
        for ln in lines:
            self._mount_main(Static(ln, classes="stream-line"))
        rest = len(code.split("\n")) - 16
        if rest > 0:
            self._mount_main(Static(Text(f"│ … +{rest} строк", style=DIM), classes="stream-line"))
        self._mount_main(Static(Text("└", style=CYAN), classes="stream-line"))

    def _refresh_context_meter(self) -> None:
        used = self._context_used
        total = self._context_total
        pct = round(100 * used / total) if total > 0 else 0
        pct = max(0, min(100, pct))
        bar_w = 16
        filled = round(bar_w * pct / 100)
        filled = max(0, min(bar_w, filled))
        bar = "[" + "=" * filled + "-" * (bar_w - filled) + "]"
        if pct < 50:
            pct_style = GREEN
        elif pct < 80:
            pct_style = YELLOW
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
        self.post_message(ChatSubmitted(text, imgs))

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

    @on(Button.Pressed, "#send-btn")
    def on_send_click(self) -> None:
        self._submit_chat_text()

    @on(Button.Pressed, "#stop-btn")
    def on_stop_click(self) -> None:
        self.post_message(StopRequested())

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

    def add_external_model(self, model_id: str) -> None:
        short = model_id.split("/")[-1] if "/" in model_id else model_id
        if len(short) > 25:
            short = short[:22] + "…"
        self._models.append({"name": short, "id": model_id})
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
            sel.value = model_id
            self.post_message(ModelChanged(model_id))
        except Exception:
            pass
