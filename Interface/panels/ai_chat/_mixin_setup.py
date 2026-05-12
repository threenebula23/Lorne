"""Mixin fragment for :class:`AIChatPanel` (split from former ai_chat.py)."""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from Agent.runtime_paths import env_pref

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

from rich.markdown import Markdown
from rich.text import Text

from ._constants import (
    MODES,
    PURPLE,
    PURPLE_LIGHT,
    GRAY,
    GREEN,
    RED,
    YELLOW,
    DIM,
    BLUE,
    CYAN,
    MARKDOWN_SYNTAX_THEME_MAP,
    _SYNTAX_OPTIONS,
    _WRITE_TOOLS,
    _WEB_TOOLS,
    _CHAT_IMAGE_EXT,
)
from ._messages import (
    ChatSubmitted,
    ModelChanged,
    ModeToggled,
    StopRequested,
    RollbackRequested,
    DeepCheckpointAction,
    ChatFilePickerScreen,
)
from ._helpers import _split_thoughts_and_body, _format_path_for_chip, _syntax_theme
from ._blocks import AssistantMessageBlock, UserMessageBlock

class AIChatPanelSetupMixin:
    def __init__(self, models: Optional[List[Dict]] = None,
                 current_model: str = "", **kwargs):
        """
        Параметры:
            models: Список моделей для ``Select`` (id, name, …).
            current_model: Текущий идентификатор выбранной модели.
            **kwargs: Аргументы Textual ``Vertical``.
        """
        super().__init__(**kwargs)
        self._models = models or []
        self._current_model = current_model
        self._current_mode = "Agent"
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
        """Подтянуть модели из prefs, собрать поле ввода, приветствие, TextArea-тему."""
        self._load_extra_models_from_prefs()
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
        sel_value = self._current_model or "default"
        _opt_ids = {pair[1] for pair in model_options}
        if sel_value not in _opt_ids:
            sel_value = model_options[0][1]

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
            Select(model_options, value=sel_value,
                   id="model-select", allow_blank=False),
            Select(mode_options, value="agent", id="mode-select", allow_blank=False),
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
        glyph = str(prefs.get("cli_prompt_glyph", "❯"))
        self._settings_row(
            content, "Приглашение CLI",
            Input(value=glyph, id="sp-cli-glyph", placeholder="❯"),
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
        prof = env_pref("PROFILE", "balanced").lower()
        if prof not in ("fast", "balanced", "quality"):
            prof = "balanced"

        # ── Card 1: profile + tool toggles ──────────────────────────────
        tools_card = Vertical(classes="settings-card", id="sa-tools-card")
        content.mount(tools_card)
        tools_card.mount(self._settings_title("Профиль агента и тулы"))
        tools_card.mount(Label(
            "Эти настройки применяются во всех режимах (Agent / Ask / Creator / Research / Deep / Brainer) "
            "и ко всем моделям — локальным и удалённым.",
            classes="settings-card-subtitle",
        ))
        self._settings_row(
            tools_card, "Профиль Lorne",
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
        from Interface.branding import APP_DISPLAY_NAME
        self._mount_main(Static(Text(APP_DISPLAY_NAME, style=f"bold {colors['accent']}")))
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
