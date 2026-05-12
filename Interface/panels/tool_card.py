"""Compact, pretty cards for tool invocations shown in the chat stream.

Replaces the old one-liner ``← read_file  a.py`` rendering. Each card is
collapsible so read-heavy sessions don't drown the user in file content;
the header always shows the gist (file name, line range, size) while the
body is hidden by default and only expands on demand.

Routing: ``TUIBridge.on_tool_result`` — ``plan_tool`` → :class:`PlanToolCardBlock`;
остальные (кроме мутаций в ``_WRITE_TOOLS``) → :class:`ToolCardBlock` с :func:`_summarize`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static


# Tools we render as cards. Write tools are still handled by CodeDiffBlock
# (the diff is strictly more useful than a textual recap); cards here are
# for "read-only" / "did an action" tools.
# Подмножество для совместимости; в TUI карточки для всех тулов кроме ``_WRITE_TOOLS``.
PRETTY_TOOL_NAMES = frozenset({
    "read_file",
    "read_file_lines",
    "list_files",
    "search_code",
    "grep",
    "run_command",
    "terminal_run",
    "run_python",
    "execute_code",
    "web_search",
    "web_fetch",
    "web_search_and_read",
})


def _accent_color() -> str:
    try:
        from Interface.ui_prefs import load_prefs
        from Interface.themes import get_theme
        prefs = load_prefs()
        theme = get_theme(str(prefs.get("theme", "Purple Dark")))
        return str(prefs.get("accent_color") or theme.get("accent") or "#8B5CF6")
    except Exception:
        return "#8B5CF6"


def _summarize(tool_name: str, result: Any) -> Dict[str, str]:
    """Return ``{"headline", "meta", "body"}`` for a tool invocation."""
    headline = tool_name
    meta = ""
    body = ""

    def _elapsed_suffix(d: Any) -> str:
        if not isinstance(d, dict):
            return ""
        e = d.get("elapsed_seconds")
        if e is None:
            return ""
        try:
            return f"⏱ {float(e):.2f}s"
        except Exception:
            return ""

    if isinstance(result, dict):
        # read_file / read_file_lines
        if tool_name in ("read_file", "read_file_lines"):
            fn = str(result.get("filename") or result.get("path") or "?")
            total = result.get("total_lines") or result.get("lines")
            start = result.get("start_line") or result.get("start")
            end = result.get("end_line") or result.get("end")
            headline = f"📖 {Path(fn).name}"
            bits = [fn]
            if start and end:
                bits.append(f"строки {start}-{end}")
            if total:
                bits.append(f"всего {total}")
            meta = "  ·  ".join(bits)
            content = result.get("content") or ""
            body = str(content)[:4000]

        elif tool_name == "list_files":
            fn = str(result.get("path") or result.get("directory") or ".")
            items = (
                result.get("entries")
                or result.get("files")
                or result.get("items")
                or []
            )
            headline = f"🗂 {fn}"
            meta = f"{len(items)} записей"
            if isinstance(items, list):
                preview = items[:40]
                lines = []
                for it in preview:
                    if isinstance(it, dict):
                        name = it.get("name") or it.get("path") or ""
                        t = str(it.get("type") or "").lower()
                        is_dir = bool(it.get("is_dir")) or t == "dir"
                        kind = "/" if is_dir else ""
                        lines.append(f"{name}{kind}")
                    else:
                        lines.append(str(it))
                if len(items) > 40:
                    lines.append(f"… +{len(items) - 40} ещё")
                body = "\n".join(lines)

        elif tool_name in ("search_code", "grep", "search_in_files"):
            q = str(
                result.get("query")
                or result.get("pattern")
                or result.get("search")
                or "",
            )
            matches = (
                result.get("matches")
                or result.get("results")
                or result.get("hits")
                or []
            )
            headline = f"🔎 {q or tool_name}"
            meta = f"{len(matches)} совпадений"
            if isinstance(matches, list):
                lines = []
                for m in matches[:30]:
                    if isinstance(m, dict):
                        path = m.get("file") or m.get("path") or ""
                        line = m.get("line") or m.get("line_number") or ""
                        snip = m.get("text") or m.get("match") or m.get("snippet") or ""
                        lines.append(f"{path}:{line}  {snip[:120]}")
                    else:
                        lines.append(str(m)[:180])
                body = "\n".join(lines)

        elif tool_name == "find_in_file":
            fp = str(result.get("file_path") or result.get("path") or "?")
            matches = result.get("matches") or []
            headline = f"📌 {Path(fp).name}"
            meta = fp
            if isinstance(matches, list):
                body = "\n".join(
                    str(x.get("line", x)) if isinstance(x, dict) else str(x)
                    for x in matches[:40]
                )

        elif tool_name == "rag_search":
            q = str(result.get("query") or "")
            hits = result.get("results") or result.get("hits") or []
            headline = f"🧠 RAG · {q[:56]}"
            meta = f"{len(hits)} хитов  ·  index≈{result.get('index_size', '?')} чанков"
            if isinstance(hits, list):
                lines = []
                for h in hits[:20]:
                    if isinstance(h, dict):
                        p = h.get("path") or h.get("file") or ""
                        sc = h.get("score")
                        sn = (h.get("snippet") or h.get("text") or "")[:200]
                        lines.append(f"{p}  [{sc}]  {sn}")
                    else:
                        lines.append(str(h)[:220])
                body = "\n".join(lines)

        elif tool_name == "reasoning_tool":
            act = str(result.get("action") or "")
            headline = f"💭 {act or 'reasoning'}"
            if act == "think" or "thought" in result:
                body = str(result.get("thought") or result.get("content") or "")[:4000]
            elif act in ("diff", "show_diff"):
                meta = str(result.get("path") or "")
                body = str(result.get("detail") or result.get("summary") or "")[:2000]
            else:
                meta = str(result.get("path") or "")
                body = str(result.get("analysis") or result.get("content") or "")[:4000]

        elif tool_name == "git_ops":
            act = str(result.get("action") or "")
            headline = f"📎 git {act or 'ops'}"
            body = json.dumps(result, ensure_ascii=False, default=str)[:3500]

        elif tool_name == "library_context":
            headline = "📚 Library"
            meta = str(result.get("library_name") or result.get("library") or "")
            body = str(result.get("content") or result.get("text") or result.get("docs") or "")[:4000]

        elif tool_name == "project_brain_tool":
            headline = "🧩 Project brain"
            if result.get("ok"):
                n = result.get("brain_chunks_indexed")
                wn = len(result.get("written") or [])
                brp = str(result.get("brain_rel_path") or "").strip()
                meta = f"ok  ·  chunks={n}  ·  files={wn}"
                if brp:
                    meta = f"{meta}  ·  {brp}"
            else:
                meta = str(result.get("error") or "")
            body = json.dumps(
                {k: v for k, v in result.items() if k not in ("context",)},
                ensure_ascii=False,
                default=str,
            )[:3500]

        elif tool_name == "file_versions_tool":
            headline = "📜 Версии файла"
            meta = str(result.get("path") or "")
            body = json.dumps(result, ensure_ascii=False, default=str)[:3500]

        elif tool_name == "get_file_line_count":
            headline = f"📏 {Path(str(result.get('path') or '?')).name}"
            meta = str(result.get("path") or "")
            body = f"строк: {result.get('line_count', result.get('lines', '?'))}"

        elif tool_name == "run_package_script":
            headline = "📦 npm/pnpm"
            meta = str(result.get("script") or result.get("command") or "")
            body = str(result.get("stdout") or result.get("output") or "")[:2500]

        elif tool_name == "download_file":
            headline = "⬇ Download"
            meta = str(result.get("url") or "")
            body = str(result.get("path") or result.get("dest") or "")[:500]

        elif tool_name in ("ocr_tool", "ocr_read_file_soft", "ocr_read_image_medium", "ocr_read_photo_strong"):
            headline = "👁 OCR"
            body = str(result.get("text") or result.get("content") or json.dumps(result, default=str))[:4000]

        elif tool_name == "office_document_read":
            headline = "📄 Office read"
            meta = str(result.get("path") or result.get("file_path") or "")
            body = str(result.get("text") or result.get("content") or "")[:4000]

        elif tool_name in ("docx_write_tool", "docxedit_tool", "docx_document_advanced_ops"):
            headline = f"📝 {tool_name.replace('_', ' ')}"
            meta = str(result.get("file_path") or result.get("path") or "")
            body = json.dumps(result, ensure_ascii=False, default=str)[:3500]

        elif tool_name in ("pdf_styled_document_create", "create_pdf"):
            headline = "📕 PDF"
            meta = str(result.get("path") or result.get("file_path") or "")
            body = json.dumps(result, ensure_ascii=False, default=str)[:2000]

        elif tool_name in ("headless_browser", "playwright_sync"):
            headline = f"🌍 {tool_name}"
            meta = str(result.get("url") or "")
            body = json.dumps(result, ensure_ascii=False, default=str)[:3000]

        elif tool_name in ("start_background_task", "get_background_result"):
            headline = "⏳ " + tool_name.replace("_", " ")
            body = json.dumps(result, ensure_ascii=False, default=str)[:3000]

        elif tool_name == "ask_user":
            headline = "❓ ask_user"
            body = json.dumps(result, ensure_ascii=False, default=str)[:2000]

        elif tool_name == "code_interpreter":
            headline = "🐍 code_interpreter"
            body = str(result.get("output") or result.get("stdout") or result.get("result") or "")[:4000]

        elif tool_name == "load_plan":
            headline = "📋 План (load)"
            body = json.dumps(result, ensure_ascii=False, default=str)[:3000]

        elif tool_name in ("save_plan", "update_plan", "clear_plan"):
            headline = f"📋 {tool_name}"
            body = json.dumps(result, ensure_ascii=False, default=str)[:3000]

        elif tool_name in ("run_command", "terminal_run", "run_python", "execute_code"):
            cmd = str(result.get("command") or result.get("cmd") or
                      result.get("code") or "")
            rc = result.get("return_code")
            if rc is None:
                rc = result.get("returncode")
            stdout = str(result.get("stdout") or "")
            stderr = str(result.get("stderr") or "")

            first_line = (cmd.splitlines() or [""])[0]
            headline = f"⌨  {first_line[:80] or tool_name}"
            if rc is not None:
                meta = f"rc={rc}" + ("  ✓" if rc == 0 else "  ✗")
            else:
                meta = "executed"

            body_parts = []
            if cmd:
                body_parts.append("$ " + cmd[:2000])
            if stdout:
                body_parts.append("── stdout ──\n" + stdout[:2000])
            if stderr:
                body_parts.append("── stderr ──\n" + stderr[:2000])
            body = "\n\n".join(body_parts)

        elif tool_name in ("web_search", "web_search_and_read"):
            q = str(result.get("query") or "")
            results = result.get("results") or []
            headline = f"🌐 {q[:60]}"
            meta = f"{len(results)} результатов"
            if isinstance(results, list):
                lines = []
                for r in results[:10]:
                    if isinstance(r, dict):
                        ti = r.get("title") or ""
                        ur = r.get("url") or ""
                        lines.append(f"• {ti}\n  {ur}")
                body = "\n".join(lines)

        elif tool_name == "web_fetch":
            url = str(result.get("url") or "")
            title = str(result.get("title") or "")
            headline = f"🌐 {title or url[:60]}"
            meta = url
            body = str(result.get("content") or result.get("text") or "")[:2000]

        elif tool_name in ("write_file", "edit_file", "replace_file_lines",
                           "insert_file_lines", "create_code_file"):
            fn = str(result.get("path") or result.get("file_path") or "?")
            headline = f"✏ {Path(fn).name}"
            meta = fn
            action = str(result.get("action") or tool_name)
            body = f"action: {action}"

        else:
            headline = f"🔧 {tool_name}"
            meta = ", ".join(str(k) for k in list(result.keys())[:10])
            try:
                body = json.dumps(result, ensure_ascii=False, default=str)[:4000]
            except Exception:
                body = str(result)[:4000]

        if not body and isinstance(result.get("error"), str):
            body = f"error: {result['error']}"

        # Prepend elapsed time to meta so every card has a timer.
        el = _elapsed_suffix(result)
        if el:
            meta = f"{el}  ·  {meta}" if meta else el

    elif isinstance(result, str):
        headline = tool_name
        body = result[:2000]

    return {
        "headline": headline or tool_name,
        "meta": meta or "",
        "body": body or "",
    }


def _plan_card_summary(result: Any) -> Dict[str, str]:
    """Build headline/meta/body for :class:`PlanToolCardBlock`."""
    headline = "📋 План"
    meta = ""
    body = ""

    def _elapsed_suffix(d: Any) -> str:
        if not isinstance(d, dict):
            return ""
        e = d.get("elapsed_seconds")
        if e is None:
            return ""
        try:
            return f"⏱ {float(e):.2f}s"
        except Exception:
            return ""

    if not isinstance(result, dict):
        return {"headline": headline, "meta": "", "body": str(result)[:4000]}

    el = _elapsed_suffix(result)
    err = result.get("error")
    if err:
        meta = f"ошибка: {err}"
        parts = []
        d = result.get("detail")
        if d:
            parts.append(str(d))
        h = result.get("hint")
        if h:
            parts.append(str(h))
        body = "\n\n".join(parts)

    _pa = str(result.get("_plan_action") or "")
    if not err:
        if _pa == "save_plan" and result.get("ok"):
            n = result.get("step_count")
            meta = f"save · шагов: {n}" if n is not None else "save"
            pp = result.get("plan_path")
            if pp:
                body = str(pp)
        elif _pa == "load_plan":
            plan = result.get("plan")
            if not result.get("ok") or not plan:
                meta = "load · плана нет"
            else:
                meta = f"load · {str(plan.get('title') or 'План')}"
                steps = plan.get("steps") or []
                if isinstance(steps, list):
                    icons = {
                        "pending": "○",
                        "in_progress": "◐",
                        "completed": "✓",
                        "blocked": "⊘",
                    }
                    lines = []
                    for s in steps:
                        if isinstance(s, dict):
                            st = str(s.get("status") or "pending")
                            ic = icons.get(st, "·")
                            txt = str(s.get("text") or "")
                            note = str(s.get("note") or "").strip()
                            line = f"{ic} {txt}"
                            if note:
                                line += f"  — {note}"
                            lines.append(line)
                        else:
                            lines.append(str(s))
                    body = "\n".join(lines)
        elif _pa == "update_plan":
            if result.get("ok"):
                meta = (
                    f"update · шаг {result.get('step_index')} → "
                    f"{result.get('status')}"
                )
                pp = result.get("plan_path")
                if pp:
                    body = str(pp)
            else:
                meta = f"ошибка: {result.get('error', 'update')}"
                body = str(result.get("detail") or "")
        elif _pa == "clear_plan":
            meta = "clear"
            if result.get("ok"):
                body = "План удалён"
            else:
                body = str(
                    result.get("reason")
                    or result.get("detail")
                    or result.get("error")
                    or "отменено"
                )
        elif not meta and not body:
            meta = "plan_tool"
            # Compact fallback for unexpected dict shape
            try:
                import json as _json
                body = _json.dumps(result, ensure_ascii=False)[:2000]
            except Exception:
                body = str(result)[:2000]

    if el:
        meta = f"{el}  ·  {meta}" if meta else el

    return {"headline": headline, "meta": meta or "", "body": body or ""}


class ToolCardBlock(Vertical):
    """A collapsible card showing a tool's invocation + result."""

    DEFAULT_CSS = """
    ToolCardBlock {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 0 0 0;
        background: transparent;
        border: round #2D2D3D;
    }
    ToolCardBlock #tool-card-header {
        height: auto;
        layout: horizontal;
        padding: 0 1 0 1;
    }
    ToolCardBlock #tool-card-toggle {
        min-width: 3; width: 3; height: 1;
        margin: 0 1 0 0; padding: 0;
        background: transparent;
        border: none;
        color: #E5E7EB;
    }
    ToolCardBlock #tool-card-toggle:hover { background: transparent; color: #F3F4F6; }
    ToolCardBlock .tool-card-title {
        height: auto;
        width: 1fr;
    }
    ToolCardBlock .tool-card-meta {
        height: auto;
        color: #6B7280;
        padding: 0 1 1 4;
    }
    ToolCardBlock .tool-card-body {
        height: auto;
        padding: 1 1 1 1;
        display: none;
        color: #D1D5DB;
    }
    ToolCardBlock.-expanded .tool-card-body { display: block; }
    """

    def __init__(self, tool_name: str, result: Any, *, expanded: bool = False,
                 **kwargs):
        super().__init__(**kwargs)
        self._tool_name = str(tool_name or "")
        self._expanded = bool(expanded)
        self._summary = _summarize(tool_name, result)

    def compose(self) -> ComposeResult:
        accent = _accent_color()
        title = Text()
        title.append(self._summary["headline"], style=f"bold {accent}")
        title.append("  ·  ", style="#6B7280")
        title.append(self._tool_name, style="#9CA3AF")

        yield Horizontal(
            Button("▸", id="tool-card-toggle"),
            Static(title, classes="tool-card-title"),
            id="tool-card-header",
        )
        if self._summary["meta"]:
            yield Static(Text(self._summary["meta"], style="#6B7280"),
                         classes="tool-card-meta")
        if self._summary["body"]:
            yield Static(Text(self._summary["body"], style="#D1D5DB"),
                         classes="tool-card-body")

    def on_mount(self) -> None:
        if self._expanded and self._summary["body"]:
            self.add_class("-expanded")
            try:
                self.query_one("#tool-card-toggle", Button).label = "▾"
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if (event.button.id or "") != "tool-card-toggle":
            return
        event.stop()
        if not self._summary["body"]:
            return
        self._expanded = not self._expanded
        if self._expanded:
            self.add_class("-expanded")
            event.button.label = "▾"
        else:
            self.remove_class("-expanded")
            event.button.label = "▸"


class PlanToolCardBlock(Vertical):
    """Collapsible card for ``plan_tool`` results (plan steps, errors, timings)."""

    DEFAULT_CSS = """
    PlanToolCardBlock {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 0 0 0;
        background: transparent;
        border: round #2D2D3D;
    }
    PlanToolCardBlock #plan-card-header {
        height: auto;
        layout: horizontal;
        padding: 0 1 0 1;
    }
    PlanToolCardBlock #plan-card-toggle {
        min-width: 3; width: 3; height: 1;
        margin: 0 1 0 0; padding: 0;
        background: transparent;
        border: none;
        color: #E5E7EB;
    }
    PlanToolCardBlock #plan-card-toggle:hover { background: transparent; color: #F3F4F6; }
    PlanToolCardBlock .plan-card-title {
        height: auto;
        width: 1fr;
    }
    PlanToolCardBlock .plan-card-meta {
        height: auto;
        color: #6B7280;
        padding: 0 1 1 4;
    }
    PlanToolCardBlock .plan-card-body {
        height: auto;
        padding: 1 1 1 1;
        display: none;
        color: #D1D5DB;
    }
    PlanToolCardBlock.-expanded .plan-card-body { display: block; }
    """

    def __init__(self, result: Any, *, expanded: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._expanded = bool(expanded)
        self._summary = _plan_card_summary(result)

    def compose(self) -> ComposeResult:
        accent = _accent_color()
        title = Text()
        title.append(self._summary["headline"], style=f"bold {accent}")
        title.append("  ·  ", style="#6B7280")
        title.append("plan_tool", style="#9CA3AF")

        yield Horizontal(
            Button("▸", id="plan-card-toggle"),
            Static(title, classes="plan-card-title"),
            id="plan-card-header",
        )
        if self._summary["meta"]:
            yield Static(Text(self._summary["meta"], style="#6B7280"),
                         classes="plan-card-meta")
        if self._summary["body"]:
            yield Static(Text(self._summary["body"], style="#D1D5DB"),
                         classes="plan-card-body")

    def on_mount(self) -> None:
        if self._expanded and self._summary["body"]:
            self.add_class("-expanded")
            try:
                self.query_one("#plan-card-toggle", Button).label = "▾"
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if (event.button.id or "") != "plan-card-toggle":
            return
        event.stop()
        if not self._summary["body"]:
            return
        self._expanded = not self._expanded
        if self._expanded:
            self.add_class("-expanded")
            event.button.label = "▾"
        else:
            self.remove_class("-expanded")
            event.button.label = "▸"
