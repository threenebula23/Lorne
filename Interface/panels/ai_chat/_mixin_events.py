"""Mixin fragment for :class:`AIChatPanel` (split from former ai_chat.py)."""
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

from ._accent_dialog import _AccentPaletteDialog
from ._constants import _ACCENT_COLORS

class AIChatPanelEventsMixin:
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

    @on(Input.Changed, "#sp-cli-glyph")
    def on_sp_cli_glyph_changed(self, event: Input.Changed) -> None:
        raw = (event.value or "").strip()
        g = raw[:12] if raw else "❯"
        try:
            from Interface.ui_prefs import save_prefs
            save_prefs(cli_prompt_glyph=g)
        except Exception:
            pass

    def on_sa_profile(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        os.environ["LORNE_PROFILE"] = str(event.value)
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
