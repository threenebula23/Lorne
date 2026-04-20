"""Compact, pretty cards for tool invocations shown in the chat stream.

Replaces the old one-liner ``← read_file  a.py`` rendering. Each card is
collapsible so read-heavy sessions don't drown the user in file content;
the header always shows the gist (file name, line range, size) while the
body is hidden by default and only expands on demand.

Routing lives in ``AIChatPanel.add_tool_card`` — the bridge calls that
for any tool whose name matches :data:`PRETTY_TOOL_NAMES`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static


# Tools we render as cards. Write tools are still handled by CodeDiffBlock
# (the diff is strictly more useful than a textual recap); cards here are
# for "read-only" / "did an action" tools.
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
            items = result.get("files") or result.get("items") or []
            headline = f"🗂 {fn}"
            meta = f"{len(items)} записей"
            if isinstance(items, list):
                preview = items[:40]
                lines = []
                for it in preview:
                    if isinstance(it, dict):
                        name = it.get("name") or it.get("path") or ""
                        kind = "/" if it.get("is_dir") else ""
                        lines.append(f"{name}{kind}")
                    else:
                        lines.append(str(it))
                if len(items) > 40:
                    lines.append(f"… +{len(items) - 40} ещё")
                body = "\n".join(lines)

        elif tool_name in ("search_code", "grep"):
            q = str(result.get("query") or result.get("pattern") or "")
            matches = result.get("matches") or result.get("results") or []
            headline = f"🔎 {q or 'grep'}"
            meta = f"{len(matches)} совпадений"
            if isinstance(matches, list):
                lines = []
                for m in matches[:30]:
                    if isinstance(m, dict):
                        path = m.get("file") or m.get("path") or ""
                        line = m.get("line") or m.get("line_number") or ""
                        snip = m.get("text") or m.get("match") or ""
                        lines.append(f"{path}:{line}  {snip[:120]}")
                    else:
                        lines.append(str(m)[:180])
                body = "\n".join(lines)

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
            # Always show the actual command so the user can see what
            # ran — the first line alone isn't enough for multi-line
            # scripts (``&&`` chains, heredocs, pipelines…).
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


class ToolCardBlock(Vertical):
    """A collapsible card showing a tool's invocation + result."""

    DEFAULT_CSS = """
    ToolCardBlock {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 0 0 0;
        background: #12121A;
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
    ToolCardBlock #tool-card-toggle:hover { background: #1F1B2E; }
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
