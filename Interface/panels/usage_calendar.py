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
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

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


def _log_file() -> Path:
    from Agent.runtime_paths import project_data_dir

    return project_data_dir() / "openrouter_usage.json"

# How many weeks of history to render. 52 ≈ one year.
_WEEKS = 52
# Glyphs: empty days must not use the same "full block" as activity — in many
# terminals a dark #hex cell looks identical to the brightest green.
_CELL_EMPTY = "· "  # 2 cell columns, visually distinct (no bar fill)
_CELL_FULL = "██"


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
        lf = _log_file()
        if not lf.exists():
            return {}
        raw = json.loads(lf.read_text(encoding="utf-8") or "{}")
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
        lf = _log_file()
        lf.parent.mkdir(parents=True, exist_ok=True)
        lf.write_text(
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


def _intensity(value: float, vmax: float) -> float:
    """0..1 for shading; log curve so a single huge day does not drown the rest."""
    if value <= 0 or vmax <= 0:
        return 0.0
    # log(1+k*x) spreads values when one day dominates
    k = 80.0
    return min(1.0, math.log(1.0 + k * value) / max(1e-9, math.log(1.0 + k * vmax)))


def _shade_for_intensity(t: float) -> str:
    if t <= 0:
        return _EMPTY
    if t < 0.25:
        return _GREEN_SHADES[0]
    if t < 0.5:
        return _GREEN_SHADES[1]
    if t < 0.75:
        return _GREEN_SHADES[2]
    return _GREEN_SHADES[3]


def _scale_max_from_dailies(data: Dict[str, float]) -> float:
    """Max of per-day $ (excludes __cumulative_total__)."""
    m = 0.0
    for k, v in data.items():
        if k == "__cumulative_total__":
            continue
        try:
            m = max(m, float(v))
        except Exception:
            continue
    return m


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
        vmax = _scale_max_from_dailies(data)

        grid = _iter_calendar_dates()
        # Render row-by-row so the output shape stays stable on narrow terminals.
        # Each day is 2 terminal columns: «·» for $0, «██»+colour for $>0.
        months_row = self._render_months_row(grid)
        rows: List[Text] = []
        # Пн..Вс — одна буква, чтобы сетка оставалась компактной
        weekday_labels = ("П", "В", "С", "Ч", "П", "С", "В")
        for r in range(7):
            line = Text()
            line.append(f"{weekday_labels[r]} ", style=_DIM)
            for col in grid:
                d = col[r]
                if d is None:
                    line.append("  ", style="")
                    continue
                v = float(data.get(d.isoformat(), 0.0) or 0.0)
                if v <= 0 or vmax <= 0:
                    line.append(_CELL_EMPTY, style=_DIM)
                    continue
                t_int = _intensity(v, vmax)
                shade = _shade_for_intensity(t_int)
                line.append(_CELL_FULL, style=shade)
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
        """Метка в колонке, где в эту неделю попадает 1-е число (01..12), 2 знака = ширина клетки."""
        return _format_months_row_for_grid(grid, _DIM)

    def _render_legend(self) -> Text:
        t = Text()
        t.append("Меньше ", style=_DIM)
        t.append(_CELL_EMPTY, style=_DIM)
        t.append(" ", style=_DIM)
        for shade in _GREEN_SHADES:
            t.append("██", style=shade)
        t.append(" Больше", style=_DIM)
        return t


def _format_months_row_for_grid(
    grid: List[List[Optional[date]]],
    dim_style: str,
) -> Text:
    """Строка месяцев: «01»..«12» в колонке недели, где есть 1-е число (2 символа = ширина дня)."""
    labels: List[str] = ["  " for _ in grid]
    seen_ym: Set[Tuple[int, int]] = set()
    for _ci, col in enumerate(grid):
        d1 = next((d for d in col if d is not None and d.day == 1), None)
        if d1 is not None:
            key = (d1.year, d1.month)
            if key not in seen_ym:
                seen_ym.add(key)
                labels[_ci] = f"{d1.month:02d}"
    out = Text()
    out.append("  ", style=dim_style)
    for lbl in labels:
        out.append(lbl, style=dim_style)
    return out


def render_cli_usage_calendar_text() -> Text:
    """Календарь расходов OpenRouter для Rich Panel в CLI (те же данные, что в TUI)."""
    try:
        from Interface.visualization import _cli_p

        pal = _cli_p()
        dim = pal.get("fg2", _DIM)
        acc = pal.get("accent", "#8B5CF6")
    except Exception:
        dim = _DIM
        acc = "#8B5CF6"

    data = _load_log()
    total = float(data.get("__cumulative_total__", 0.0) or 0.0)
    window_sum = sum(
        float(v) for k, v in data.items() if k != "__cumulative_total__"
    )
    usd_total = max(total, window_sum)

    vmax = _scale_max_from_dailies(data)
    n_days_charged = sum(
        1 for k, v in data.items()
        if k != "__cumulative_total__" and (float(v) if v else 0) > 0
    )

    out = Text()
    out.append("Расход OpenRouter (календарь по дням)\n", style=dim)
    out.append(f"${usd_total:,.4f}", style=f"bold {acc}")
    out.append("   накоплено (API / локальный лог)\n", style=dim)
    if n_days_charged <= 1 and usd_total > 0:
        out.append(
            "Один снимок: весь накопит. расход в один день; по дням — после регулярных "
            "проверок /balance (дельта в день). «·» = $0 в этот день.\n",
            style=dim,
        )
    out.append("\n", style=dim)

    grid = _iter_calendar_dates()
    out.append(_format_months_row_for_grid(grid, dim))
    out.append("\n")
    weekday_labels = ("П", "В", "С", "Ч", "П", "С", "В")
    for r in range(7):
        line = Text()
        line.append(f"{weekday_labels[r]} ", style=dim)
        for col in grid:
            d = col[r]
            if d is None:
                line.append("  ", style="")
                continue
            v = float(data.get(d.isoformat(), 0.0) or 0.0)
            if v <= 0 or vmax <= 0:
                line.append(_CELL_EMPTY, style=dim)
                continue
            t_int = _intensity(v, vmax)
            shade = _shade_for_intensity(t_int)
            line.append(_CELL_FULL, style=shade)
        out.append(line)
        if r < 6:
            out.append("\n")
    out.append("\n")
    out.append("Меньше ", style=dim)
    out.append(_CELL_EMPTY, style=dim)
    out.append(" ", style=dim)
    for shade in _GREEN_SHADES:
        out.append("██", style=shade)
    out.append(" Больше", style=dim)
    return out
