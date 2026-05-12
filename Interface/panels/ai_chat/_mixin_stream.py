"""Mixin fragment for :class:`AIChatPanel` (split from former ai_chat.py)."""
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
    from Interface.panels.tool_card import (
        ToolCardBlock,
        PlanToolCardBlock,
        PRETTY_TOOL_NAMES,
    )
except Exception:  # pragma: no cover
    ToolCardBlock = None  # type: ignore[misc, assignment]
    PlanToolCardBlock = None  # type: ignore[misc, assignment]
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

class AIChatPanelStreamMixin:
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
        body = (body or "").strip()
        if usage:
            inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            if (not inp) and (not out) and body and not usage.get("_estimated"):
                out = max(8, len(body) // 3)
            if inp or out:
                self._lifetime_prompt += max(0, inp)
                self._lifetime_completion += max(0, out)
        footer = self._footer_for_assistant(usage)
        if not body:
            self._mount_file_changes_table()
            self._mount_sources_widget()
            self.reset_round_file_metrics()
            self._refresh_context_meter()
            return
        # Двойная эмиссия одного и того же финального ответа (например LangGraph
        # после узла brain_sync) — один пузырь в UI.
        try:
            import hashlib

            _h = hashlib.sha256(body.encode("utf-8", errors="ignore")).hexdigest()[:20]
        except Exception:
            _h = str(len(body))
        if self._is_duplicate_render(f"assistant:{_h}", window_sec=15.0):
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

    def add_plan_tool_card(self, result: Any) -> None:
        """Pretty card for ``plan_tool`` (steps, statuses, JSON hints)."""
        if PlanToolCardBlock is None:
            return self.add_tool_result("plan_tool", str(result)[:120])
        dedup_key = f"plancard:{str(result)[:120]}"
        if self._is_duplicate_render(dedup_key):
            return
        try:
            self._mount_main(PlanToolCardBlock(result))
        except Exception:
            self.add_tool_result("plan_tool", str(result)[:120])

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
                        checkpoints: int = 0, model: str = "", current_step: int = 0) -> None:
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
        if int(current_step or 0) > 0:
            label.append(f"шаг {int(current_step)}  ·  ", style="#9CA3AF")
        label.append(f"⏱ {elapsed or '00:00'}", style="#E5E7EB")
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

    def apply_model_context_limit(self, model_id: str, fallback_total: int) -> None:
        """Sync context window label with the model catalog entry when available."""
        total = max(0, int(fallback_total or 0))
        mid = (model_id or "").strip()
        for m in self._models:
            if str(m.get("id") or "") != mid:
                continue
            c = int(m.get("ctx") or 0)
            if c > 0:
                total = max(total, c)
            break
        if total > 0:
            self._context_total = total
        self.update_model(mid)
        self.update_context(self._context_used, self._context_total)

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
