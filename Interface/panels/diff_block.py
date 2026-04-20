"""Side-by-side code diff shown in the chat stream after a file-editing tool.

Layout (left → right, per user request):
    NEW (current)          OLD (before)
The left column shows the post-edit content, the right column shows the
pre-edit content. Added lines are highlighted with the theme's success
colour, removed lines with the error colour, unchanged context uses the
dim foreground so changes visually pop without adding extra hues.

Only the *changed* region is rendered, padded by a few lines of context,
capped at a few dozen rows to keep the chat compact.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import List, Optional, Tuple

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Static


# Palette that never changes — green/red are semantic.
OK_GREEN = "#10B981"
ERR_RED = "#EF4444"
FG2_DIM = "#6B7280"
FG_MAIN = "#E5E7EB"


def _accent_color() -> str:
    try:
        from Interface.ui_prefs import load_prefs
        from Interface.themes import get_theme
        prefs = load_prefs()
        theme = get_theme(str(prefs.get("theme", "Purple Dark")))
        return str(prefs.get("accent_color") or theme.get("accent") or "#8B5CF6")
    except Exception:
        return "#8B5CF6"


def diff_stats(before: str, after: str) -> Tuple[int, int]:
    """Count the number of added / removed lines between two texts."""
    b = (before or "").splitlines()
    a = (after or "").splitlines()
    added = 0
    removed = 0
    for line in difflib.ndiff(b, a):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def _pair_diff_lines(
    before: str,
    after: str,
    max_rows: int = 40,
    context: int = 2,
) -> List[Tuple[str, str, str]]:
    """Produce a compact list of paired diff rows.

    Each row is ``(kind, new_line, old_line)`` where *kind* is one of:
    ``"eq"``, ``"add"``, ``"del"``, ``"chg"`` (both sides differ).
    Unchanged context far from any change is collapsed to at most *context*
    lines before and after each hunk.
    """
    b = (before or "").splitlines()
    a = (after or "").splitlines()

    matcher = difflib.SequenceMatcher(a=b, b=a, autojunk=False)

    rows: List[Tuple[str, str, str]] = []
    gap_marker_added = False
    blocks = matcher.get_opcodes()

    for op_idx, (op, i1, i2, j1, j2) in enumerate(blocks):
        if op == "equal":
            block_len = i2 - i1
            has_prev = op_idx > 0
            has_next = op_idx < len(blocks) - 1
            take_lead = context if has_prev else 0
            take_tail = context if has_next else 0
            if block_len <= take_lead + take_tail:
                lead_range = range(i1, i2)
                tail_range: range = range(i1, i1)  # empty
            else:
                lead_range = range(i1, i1 + take_lead)
                tail_range = range(i2 - take_tail, i2)

            for idx in lead_range:
                rows.append(("eq", a[j1 + (idx - i1)], b[idx]))
            if block_len > take_lead + take_tail and (has_prev and has_next):
                if not gap_marker_added or rows[-1][0] != "gap":
                    rows.append(("gap", "…", "…"))
                    gap_marker_added = True
            for idx in tail_range:
                rows.append(("eq", a[j1 + (idx - i1)], b[idx]))
            gap_marker_added = False
        elif op == "replace":
            left = a[j1:j2]
            right = b[i1:i2]
            n = max(len(left), len(right))
            for k in range(n):
                new_ln = left[k] if k < len(left) else ""
                old_ln = right[k] if k < len(right) else ""
                if new_ln and old_ln:
                    rows.append(("chg", new_ln, old_ln))
                elif new_ln:
                    rows.append(("add", new_ln, ""))
                else:
                    rows.append(("del", "", old_ln))
        elif op == "insert":
            for k in range(j1, j2):
                rows.append(("add", a[k], ""))
        elif op == "delete":
            for k in range(i1, i2):
                rows.append(("del", "", b[k]))

        if len(rows) > max_rows * 2:
            break

    if len(rows) > max_rows:
        head = rows[: max_rows - 1]
        head.append(("gap", f"… ещё {len(rows) - (max_rows - 1)} строк", "…"))
        rows = head
    return rows


def _truncate_cell(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "…"


class CodeDiffBlock(Vertical):
    """Two-column diff card: NEW on the left, OLD on the right.

    The card is collapsible — by default only a one-line summary is shown
    (file name, action, +/- line counts) and the user clicks the ▸ / ▾
    toggle to reveal the actual diff body. This keeps the chat stream
    compact when several files are touched per turn.
    """

    DEFAULT_CSS = """
    CodeDiffBlock {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 0 0 0;
        background: #12121A;
        border: round #2D2D3D;
    }
    CodeDiffBlock #diff-header-row {
        height: auto;
        layout: horizontal;
        padding: 0 1 0 1;
    }
    CodeDiffBlock #diff-toggle-btn {
        min-width: 3;
        width: 3;
        height: 1;
        margin: 0 1 0 0;
        padding: 0 0 0 0;
        background: transparent;
        border: none;
        color: #E5E7EB;
    }
    CodeDiffBlock #diff-toggle-btn:hover {
        background: #1F1B2E;
    }
    CodeDiffBlock .diff-header {
        height: auto;
        width: 1fr;
    }
    CodeDiffBlock .diff-body {
        height: auto;
        padding: 1 1 1 1;
        display: none;
    }
    CodeDiffBlock.-expanded .diff-body {
        display: block;
    }
    """

    MAX_ROWS = 28
    COL_WIDTH = 56

    def __init__(
        self,
        filename: str,
        before: str,
        after: str,
        *,
        action: str = "",
        start_expanded: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._filename = filename or ""
        self._before = before or ""
        self._after = after or ""
        self._action = (action or "").strip()
        self._header_static: Optional[Static] = None
        self._body_static: Optional[Static] = None
        self._toggle_btn: Optional[Button] = None
        self._rows_cache: List[Tuple[str, str, str]] = []
        self._expanded = bool(start_expanded)

    def _build_header(self) -> Text:
        accent = _accent_color()
        added, removed = diff_stats(self._before, self._after)
        header = Text()
        name = Path(self._filename).name if self._filename else "(unnamed)"
        header.append(" ", style="")
        header.append(name, style=f"bold {accent}")
        if self._action:
            header.append(f"  ·  {self._action}", style=FG2_DIM)
        header.append("  ·  ", style=FG2_DIM)
        header.append(f"+{added}", style=f"bold {OK_GREEN}")
        header.append("/", style=FG2_DIM)
        header.append(f"-{removed}", style=f"bold {ERR_RED}")
        return header

    def _arrow(self) -> str:
        return "▾" if self._expanded else "▸"

    def compose(self) -> ComposeResult:
        from textual.containers import Horizontal
        self._rows_cache = _pair_diff_lines(
            self._before, self._after, max_rows=self.MAX_ROWS, context=2,
        )
        self._toggle_btn = Button(self._arrow(), id="diff-toggle-btn")
        self._header_static = Static(self._build_header(), classes="diff-header")
        with Horizontal(id="diff-header-row"):
            yield self._toggle_btn
            yield self._header_static
        self._body_static = Static(self._render_body(self._rows_cache), classes="diff-body")
        yield self._body_static

    def on_mount(self) -> None:
        if self._expanded:
            self.add_class("-expanded")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self._toggle_btn:
            event.stop()
            self._expanded = not self._expanded
            if self._expanded:
                self.add_class("-expanded")
            else:
                self.remove_class("-expanded")
            if self._toggle_btn is not None:
                try:
                    self._toggle_btn.label = self._arrow()
                except Exception:
                    pass

    def refresh_accent(self) -> None:
        if self._header_static is not None:
            try:
                self._header_static.update(self._build_header())
            except Exception:
                pass
        if self._body_static is not None and self._rows_cache:
            try:
                self._body_static.update(self._render_body(self._rows_cache))
            except Exception:
                pass

    def _render_body(self, rows: List[Tuple[str, str, str]]) -> Text:
        accent = _accent_color()
        col = self.COL_WIDTH
        body = Text()

        # Column titles — NEW left, OLD right (as requested by the user).
        titles = Text()
        titles.append(_truncate_cell("◀ НОВОЕ", col).ljust(col), style=f"bold {OK_GREEN}")
        titles.append("  ", style="")
        titles.append(_truncate_cell("СТАРОЕ ▶", col).ljust(col), style=f"bold {ERR_RED}")
        body.append_text(titles)
        body.append("\n", style="")
        body.append("─" * (col * 2 + 2), style=FG2_DIM)
        body.append("\n", style="")

        if not rows:
            body.append(_truncate_cell("— без изменений —", col * 2), style=FG2_DIM)
            return body

        for kind, new_ln, old_ln in rows:
            if kind == "gap":
                gap_line = (new_ln or "…").center(col * 2 + 2)
                body.append(gap_line, style=FG2_DIM)
                body.append("\n", style="")
                continue

            new_cell = _truncate_cell(new_ln or "", col)
            old_cell = _truncate_cell(old_ln or "", col)

            if kind == "add":
                new_style = f"{OK_GREEN}"
                old_style = FG2_DIM
                new_prefix = "+ "
                old_prefix = "  "
            elif kind == "del":
                new_style = FG2_DIM
                old_style = f"{ERR_RED}"
                new_prefix = "  "
                old_prefix = "- "
            elif kind == "chg":
                new_style = f"{OK_GREEN}"
                old_style = f"{ERR_RED}"
                new_prefix = "+ "
                old_prefix = "- "
            else:  # eq
                new_style = FG_MAIN
                old_style = FG2_DIM
                new_prefix = "  "
                old_prefix = "  "

            left = (new_prefix + new_cell).ljust(col)
            right = (old_prefix + old_cell).ljust(col)

            body.append(left, style=new_style)
            body.append("  ", style=FG2_DIM)
            body.append(right, style=old_style)
            body.append("\n", style="")

        # Strip trailing newline for a tight card.
        if body.plain.endswith("\n"):
            body = body[:-1]
        return body


def read_before_after_texts(path: str, snapshot_id: Optional[str]) -> Tuple[str, str]:
    """Best-effort retrieval of the *before* and *after* content of a file.

    Uses the versioning store for the pre-edit snapshot and the on-disk
    content for the post-edit view. Either side may be empty if unavailable.
    """
    before = ""
    after = ""
    if snapshot_id:
        try:
            from Agent.versioning import get_version_content
            val = get_version_content(str(path), str(snapshot_id))
            if isinstance(val, str):
                before = val
        except Exception:
            before = ""
    try:
        p = Path(path)
        if p.exists() and p.is_file():
            after = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        after = ""
    return before, after
