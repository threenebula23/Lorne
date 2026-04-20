"""GitHub-style usage-calendar widget for OpenRouter balance display.

Shows the user's daily OpenRouter spend over the last ~year as a grid of
green squares — tiny ones for no-usage days, saturated ones for heavy
days. The big number on top is the cumulative usage reported by the
OpenRouter API (or the sum of our local log, whichever is larger).

The widget intentionally reads from a local JSON log — OpenRouter does
not expose per-day history through the `/auth/key` endpoint, so we keep
our own record. Each time the user clicks *"Проверить баланс"* we compute
the delta between the API's cumulative `usage` and the last snapshot we
stored, and attribute that delta to today. Missing days stay blank.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


# Four-shade green palette (empty → max)
_EMPTY = "#161A22"
_GREEN_SHADES: Tuple[str, ...] = (
    "#0E4429",  # 1 — quiet day
    "#006D32",  # 2
    "#26A641",  # 3
    "#39D353",  # 4 — most active
)

_DIM = "#6B7280"
_FG_MAIN = "#E5E7EB"
_LOG_FILE = Path(".tca/openrouter_usage.json")

# How many weeks of history to render. 52 ≈ one year.
_WEEKS = 52


def _accent_color() -> str:
    try:
        from Interface.ui_prefs import load_prefs
        from Interface.themes import get_theme
        prefs = load_prefs()
        theme = get_theme(str(prefs.get("theme", "Purple Dark")))
        return str(prefs.get("accent_color") or theme.get("accent") or "#8B5CF6")
    except Exception:
        return "#8B5CF6"


# ── persistence helpers ──────────────────────────────────────────────


def _load_log() -> Dict[str, float]:
    try:
        if not _LOG_FILE.exists():
            return {}
        raw = json.loads(_LOG_FILE.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = max(0.0, float(v))
        except Exception:
            continue
    return out


def _save_log(data: Dict[str, float]) -> None:
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception:
        pass


def record_cumulative_usage(total_usd: float) -> Dict[str, float]:
    """Persist today's usage delta given the cumulative total reported by OpenRouter.

    Returns the updated log. This function is idempotent within a day —
    calling it multiple times just keeps the **maximum** delta we've seen
    so far, which corresponds to the most recent snapshot.
    """
    try:
        total = max(0.0, float(total_usd))
    except Exception:
        return _load_log()

    data = _load_log()
    today = date.today().isoformat()
    meta_key = "__cumulative_total__"
    prev_total = float(data.get(meta_key, 0.0) or 0.0)
    delta = total - prev_total
    if delta < 0:
        # Server reset counters — don't invent a negative day, just re-baseline.
        delta = 0.0
    prior_today = float(data.get(today, 0.0) or 0.0)
    data[today] = prior_today + delta
    data[meta_key] = total
    _save_log(data)
    return data


def total_usage() -> float:
    data = _load_log()
    try:
        return float(data.get("__cumulative_total__", 0.0) or 0.0)
    except Exception:
        return 0.0


# ── rendering ────────────────────────────────────────────────────────


def _shade_for(value: float, vmax: float) -> str:
    if value <= 0 or vmax <= 0:
        return _EMPTY
    ratio = min(1.0, value / vmax)
    if ratio < 0.25:
        return _GREEN_SHADES[0]
    if ratio < 0.5:
        return _GREEN_SHADES[1]
    if ratio < 0.75:
        return _GREEN_SHADES[2]
    return _GREEN_SHADES[3]


def _iter_calendar_dates(weeks: int = _WEEKS) -> List[List[Optional[date]]]:
    """Build a grid: columns are weeks (oldest → newest), rows are weekdays (Mon..Sun).

    The last column ends on today; older columns extend into the past.
    """
    today = date.today()
    # Shift so the rightmost column's Sunday aligns to "this week".
    # Monday=0 … Sunday=6.
    days_since_monday = today.weekday()
    end_of_week = today + timedelta(days=(6 - days_since_monday))
    start = end_of_week - timedelta(days=(weeks * 7 - 1))
    cols: List[List[Optional[date]]] = []
    for w in range(weeks):
        col: List[Optional[date]] = []
        for r in range(7):
            d = start + timedelta(days=w * 7 + r)
            if d > today:
                col.append(None)
            else:
                col.append(d)
        cols.append(col)
    return cols


class UsageCalendar(Vertical):
    """Big-number + GitHub-style heatmap of OpenRouter daily usage."""

    DEFAULT_CSS = """
    UsageCalendar {
        height: auto;
        width: 100%;
        padding: 1 1;
        margin: 0 0 1 0;
        background: #12121A;
        border: round #2D2D3D;
    }
    UsageCalendar .uc-title {
        height: auto;
    }
    UsageCalendar .uc-grid {
        height: auto;
        padding: 1 0 0 0;
    }
    UsageCalendar .uc-legend {
        height: auto;
        padding: 1 0 0 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._title_widget: Optional[Static] = None
        self._grid_widget: Optional[Static] = None
        self._legend_widget: Optional[Static] = None

    def compose(self) -> ComposeResult:
        self._title_widget = Static(self._render_title(), classes="uc-title")
        self._grid_widget = Static(self._render_grid(), classes="uc-grid")
        self._legend_widget = Static(self._render_legend(), classes="uc-legend")
        yield self._title_widget
        yield self._grid_widget
        yield self._legend_widget

    def reload(self) -> None:
        """Re-read the log from disk and re-render."""
        self._refresh_all()

    def refresh_accent(self) -> None:
        self._refresh_all()

    # ── helpers ──────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        if self._title_widget is not None:
            try:
                self._title_widget.update(self._render_title())
            except Exception:
                pass
        if self._grid_widget is not None:
            try:
                self._grid_widget.update(self._render_grid())
            except Exception:
                pass
        if self._legend_widget is not None:
            try:
                self._legend_widget.update(self._render_legend())
            except Exception:
                pass

    def _render_title(self) -> Text:
        accent = _accent_color()
        data = _load_log()
        total = float(data.get("__cumulative_total__", 0.0) or 0.0)
        # Sum of daily entries is the number of dollars spent over the window.
        window_sum = sum(
            float(v) for k, v in data.items() if k != "__cumulative_total__"
        )
        usd_total = max(total, window_sum)

        t = Text()
        t.append("Использование OpenRouter\n", style=f"{_DIM}")
        t.append(f"${usd_total:,.4f}", style=f"bold {accent}")
        t.append("   всего", style=_DIM)
        return t

    def _render_grid(self) -> Text:
        data = _load_log()
        vmax = 0.0
        for k, v in data.items():
            if k == "__cumulative_total__":
                continue
            try:
                vmax = max(vmax, float(v))
            except Exception:
                continue

        grid = _iter_calendar_dates()
        # Render row-by-row so the output shape stays stable on narrow terminals.
        # Each cell is 2 columns wide.
        months_row = self._render_months_row(grid)
        rows: List[Text] = []
        weekday_labels = ("M", " ", "W", " ", "F", " ", " ")
        for r in range(7):
            line = Text()
            line.append(f"{weekday_labels[r]} ", style=_DIM)
            for col in grid:
                d = col[r]
                if d is None:
                    line.append("  ", style="")
                    continue
                v = float(data.get(d.isoformat(), 0.0) or 0.0)
                shade = _shade_for(v, vmax)
                # Use a filled square; background gives the colour,
                # a matching foreground keeps the glyph invisible.
                line.append("██", style=shade)
            rows.append(line)

        out = Text()
        out.append(months_row)
        out.append("\n")
        for i, row in enumerate(rows):
            out.append(row)
            if i < len(rows) - 1:
                out.append("\n")
        return out

    def _render_months_row(self, grid: List[List[Optional[date]]]) -> Text:
        """Produce a row of month labels aligned with week columns.

        We pick the first Monday-of-month visible in each column and drop a
        two-letter Russian abbreviation there. Other columns get blank spaces
        so everything stays column-aligned.
        """
        ru_short = (
            "Я", "Ф", "М", "А", "М", "И", "И", "А", "С", "О", "Н", "Д",
        )
        seen_months: Dict[int, int] = {}
        labels: List[str] = ["  " for _ in grid]
        for ci, col in enumerate(grid):
            first = next((d for d in col if d is not None), None)
            if first is None:
                continue
            if first.day <= 7 and first.month not in seen_months:
                seen_months[first.month] = ci
                labels[ci] = f"{ru_short[first.month - 1]} "
        out = Text()
        out.append("  ", style=_DIM)  # weekday gutter
        for lbl in labels:
            out.append(lbl, style=_DIM)
        return out

    def _render_legend(self) -> Text:
        t = Text()
        t.append("Меньше ", style=_DIM)
        t.append("██", style=_EMPTY)
        for shade in _GREEN_SHADES:
            t.append("██", style=shade)
        t.append(" Больше", style=_DIM)
        return t
