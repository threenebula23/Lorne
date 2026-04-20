"""Progress block displayed above the chat input while Creator Mode runs.

Two-row layout:

    Этап: planning · 42% · 00:12
    ▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░   ← grid animation

The grid is driven — the server pushes a target percent and the animation
interpolates smoothly towards that target, so the visual fill always matches
real progress. Colours follow the current theme's accent.
"""
from __future__ import annotations

import random
import time
from typing import List, Optional

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

PURPLE = "#8B5CF6"
DIM = "#2D2D3D"
GRAY = "#6B7280"


# Exposed for tests — stages increasing means a cell grows from empty → full.
_FILL_GLYPHS = ("  ", "░░", "▒▒", "▓▓", "██")


# Human-friendly labels for internal phase slugs coming from the orchestrator.
_PHASE_LABELS = {
    "starting": "запуск",
    "planning": "план",
    "routing": "маршрутизация",
    "working": "работают воркеры",
    "workers": "работают воркеры",
    "supervisor": "супервизор",
    "summary": "сборка итога",
    "done": "готово",
    "finished": "готово",
}


class CreatorProgressBlock(Vertical):
    """Full-width square-strip progress indicator for Creator Mode."""

    DEFAULT_CSS = """
    CreatorProgressBlock {
        height: auto;
        width: 100%;
        padding: 0;
        margin: 0 0 1 0;
        background: transparent;
    }
    CreatorProgressBlock .creator-progress-status {
        height: 1;
        width: 100%;
        padding: 0 1;
        margin: 0 0 0 0;
    }
    CreatorProgressBlock .creator-progress-grid {
        height: auto;
        width: 100%;
    }
    """

    ROWS = 2
    STAGES_PER_CELL = 4
    TICK_INTERVAL = 0.04          # seconds between animation ticks
    MAX_STAGES_PER_TICK = 32      # batch size — keeps UI smooth for wide terminals

    # Each cell is 2 terminal columns wide ("  " / "██"); we stay flush.
    CELL_COLS = 2

    def __init__(self, task: str = "", total_workers: int = 0, **kwargs) -> None:
        super().__init__(**kwargs)
        self._task = (task or "").strip()
        self._total_workers = int(total_workers or 0)
        self._completed_workers = 0
        self._phase = "starting"
        self._summary_line = ""
        self._finished = False
        self._start_ts = time.monotonic()

        self._cols = 60  # refreshed on mount / resize
        self._grid: List[List[int]] = []
        self._active_cells: List[tuple[int, int]] = []
        self._total_stages = 0
        self._current_stages = 0
        self._target_stages = 0
        self._target_percent = 0.0

        self._rng = random.Random()
        self._timer = None

        self._build_grid(self._cols)

    # ── composition ───────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static(
            self._render_status(),
            classes="creator-progress-status",
            id="creator-progress-status",
        )
        yield Static(
            self._render_grid(),
            classes="creator-progress-grid",
            id="creator-progress-grid",
        )

    def on_mount(self) -> None:
        self._start_ts = time.monotonic()
        try:
            self._resize_to_parent()
        except Exception:
            pass
        try:
            self._timer = self.set_interval(self.TICK_INTERVAL, self._tick)
        except Exception:
            self._timer = None
        # Refresh status once per second so the elapsed-time counter moves
        # even when the orchestrator isn't pushing new percent updates.
        try:
            self.set_interval(1.0, self._refresh_status)
        except Exception:
            pass

    def on_resize(self, event) -> None:  # type: ignore[override]
        self._resize_to_parent()


    # ── public API ────────────────────────────────────────────────

    def set_total_workers(self, total_workers: int) -> None:
        self._total_workers = max(0, int(total_workers))
        self._refresh_status()

    def update_progress(
        self,
        phase: Optional[str] = None,
        percent: Optional[float] = None,
        completed: Optional[int] = None,
        total: Optional[int] = None,
    ) -> None:
        if phase is not None:
            self._phase = str(phase).lower() or self._phase
        if total is not None:
            self._total_workers = max(0, int(total))
        if completed is not None:
            self._completed_workers = max(0, int(completed))
        if percent is not None:
            p = max(0.0, min(100.0, float(percent)))
            self._target_percent = p
            self._target_stages = int((p / 100.0) * self._total_stages)
        self._refresh_status()

    def finish(self, summary: str = "") -> None:
        self._finished = True
        self._summary_line = (summary or "").strip()
        self._phase = "done"
        self._target_stages = self._total_stages
        self._target_percent = 100.0
        self._refresh_status()

    # ── sizing ────────────────────────────────────────────────────

    def _build_grid(self, cols: int) -> None:
        cols = max(10, int(cols))
        self._cols = cols
        self._grid = [[0 for _ in range(cols)] for _ in range(self.ROWS)]
        self._active_cells = [
            (r, c) for r in range(self.ROWS) for c in range(cols)
        ]
        self._total_stages = self.ROWS * cols * self.STAGES_PER_CELL
        self._current_stages = 0
        self._target_stages = int((self._target_percent / 100.0) * self._total_stages)

    def _resize_to_parent(self) -> None:
        try:
            width = int(self.size.width or 0)
        except Exception:
            width = 0
        if width <= 0:
            try:
                width = int(self.app.size.width or 0)  # type: ignore[attr-defined]
            except Exception:
                width = 60
        cols = max(12, width // self.CELL_COLS)
        if cols == self._cols:
            return
        fraction = 0.0
        if self._total_stages > 0:
            fraction = self._current_stages / self._total_stages
        self._build_grid(cols)
        self._current_stages = int(fraction * self._total_stages)
        self._redistribute_fill()
        self._refresh_grid()

    def _redistribute_fill(self) -> None:
        stages_to_place = self._current_stages
        self._grid = [[0 for _ in range(self._cols)] for _ in range(self.ROWS)]
        self._active_cells = [
            (r, c) for r in range(self.ROWS) for c in range(self._cols)
        ]
        placed = 0
        while placed < stages_to_place and self._active_cells:
            idx = self._rng.randrange(len(self._active_cells))
            r, c = self._active_cells[idx]
            self._grid[r][c] += 1
            placed += 1
            if self._grid[r][c] >= self.STAGES_PER_CELL:
                self._active_cells[idx] = self._active_cells[-1]
                self._active_cells.pop()
        self._current_stages = placed

    # ── drawing ───────────────────────────────────────────────────

    def _accent_color(self) -> str:
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import get_theme
            prefs = load_prefs()
            theme = get_theme(str(prefs.get("theme", "Purple Dark")))
            return str(prefs.get("accent_color") or theme.get("accent") or PURPLE)
        except Exception:
            return PURPLE

    def _dim_color(self) -> str:
        return DIM

    def _elapsed_str(self) -> str:
        try:
            secs = max(0, int(time.monotonic() - self._start_ts))
        except Exception:
            secs = 0
        m, s = divmod(secs, 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _phase_label(self) -> str:
        return _PHASE_LABELS.get(self._phase, self._phase or "—")

    def _render_status(self) -> Text:
        accent = self._accent_color()
        pct = int(round(self._target_percent))
        t = Text()
        t.append("Этап: ", style=GRAY)
        t.append(self._phase_label(), style=f"bold {accent}")
        t.append("  ·  ", style=GRAY)
        t.append(f"{pct}%", style=f"bold {accent}")
        t.append("  ·  ", style=GRAY)
        t.append(self._elapsed_str(), style=accent)
        return t

    def _render_grid(self) -> Text:
        accent = self._accent_color()
        dim = self._dim_color()
        t = Text()
        for row_idx, row in enumerate(self._grid):
            for stage in row:
                glyph = _FILL_GLYPHS[min(stage, len(_FILL_GLYPHS) - 1)]
                if stage == 0:
                    t.append(glyph, style=dim)
                elif stage == len(_FILL_GLYPHS) - 1:
                    t.append(glyph, style=f"bold {accent}")
                else:
                    t.append(glyph, style=accent)
            if row_idx < len(self._grid) - 1:
                t.append("\n")
        return t

    def _refresh_grid(self) -> None:
        try:
            self.query_one("#creator-progress-grid", Static).update(self._render_grid())
        except Exception:
            pass

    def _refresh_status(self) -> None:
        try:
            self.query_one("#creator-progress-status", Static).update(self._render_status())
        except Exception:
            pass

    def refresh_accent(self) -> None:
        """Re-render with the latest accent colour (called when theme changes)."""
        self._refresh_grid()
        self._refresh_status()

    # ── animation ─────────────────────────────────────────────────

    def _tick(self) -> None:
        if self._current_stages < self._target_stages and self._active_cells:
            steps_to_add = self._target_stages - self._current_stages
            steps = min(steps_to_add, self.MAX_STAGES_PER_TICK)
            for _ in range(steps):
                if not self._active_cells:
                    break
                idx = self._rng.randrange(len(self._active_cells))
                r, c = self._active_cells[idx]
                self._grid[r][c] += 1
                self._current_stages += 1
                if self._grid[r][c] >= self.STAGES_PER_CELL:
                    self._active_cells[idx] = self._active_cells[-1]
                    self._active_cells.pop()
            self._refresh_grid()

        if self._finished and self._current_stages >= self._total_stages:
            if self._timer is not None:
                try:
                    self._timer.stop()
                except Exception:
                    pass
                self._timer = None
            try:
                self.set_timer(0.8, self._self_dismiss)
            except Exception:
                self._self_dismiss()

    def _self_dismiss(self) -> None:
        parent = self.parent
        try:
            self.remove()
        except Exception:
            pass
        try:
            if parent is not None and getattr(parent, "id", None) == "creator-progress-slot":
                parent.add_class("hidden")
        except Exception:
            pass
