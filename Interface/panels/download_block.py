"""In-chat progress bar for the ``download_file`` tool.

Rendered as a single card with:
  * filename / URL
  * progress bar (unicode blocks)
  * percentage, received/total size, throughput, elapsed time
  * ``Отменить`` button that fires the cancel flag in the Python tool

Updates in place as new ``on_download_progress`` ticks arrive from the
streaming loop. Once ``done`` fires the button is removed and the body
is rewritten with the final status (``ok`` / ``cancelled`` / ``error``).
"""
from __future__ import annotations

from typing import Optional

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static


def _accent_color() -> str:
    try:
        from Interface.ui_prefs import load_prefs
        from Interface.themes import get_theme
        prefs = load_prefs()
        theme = get_theme(str(prefs.get("theme", "Purple Dark")))
        return str(prefs.get("accent_color") or theme.get("accent") or "#8B5CF6")
    except Exception:
        return "#8B5CF6"


def _humansize(n: float) -> str:
    if n < 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    if m:
        return f"{m}м {s:02d}с"
    return f"{s}с"


def _make_bar(percent: float, width: int = 30) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(width * percent / 100)
    return "█" * filled + "░" * (width - filled)


class DownloadProgressBlock(Vertical):
    DEFAULT_CSS = """
    DownloadProgressBlock {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: #12121A;
        border: round #2D2D3D;
    }
    DownloadProgressBlock .dl-header {
        height: auto;
        text-style: bold;
    }
    DownloadProgressBlock .dl-url {
        height: auto;
        color: #6B7280;
        margin: 0 0 1 0;
    }
    DownloadProgressBlock .dl-bar {
        height: auto;
        color: #E5E7EB;
    }
    DownloadProgressBlock .dl-stats {
        height: auto;
        color: #9CA3AF;
        margin: 1 0 0 0;
    }
    DownloadProgressBlock .dl-buttons {
        height: auto;
        layout: horizontal;
        margin: 1 0 0 0;
    }
    DownloadProgressBlock .dl-buttons Button {
        margin: 0 2 0 0;
        min-width: 22;
        height: 3;
        border: round #2D2D3D;
        padding: 0 2;
        text-style: bold;
    }
    DownloadProgressBlock .dl-cancel {
        background: #2A1A1A;
        color: #FCA5A5;
    }
    DownloadProgressBlock .dl-cancel:hover {
        background: #3F1F1F;
    }
    """

    def __init__(self, download_id: str, url: str, **kwargs):
        super().__init__(**kwargs)
        self._dl_id = str(download_id)
        self._url = str(url or "")
        self._received = 0
        self._total = 0
        self._elapsed = 0.0
        self._done = False
        self._error = ""

    @property
    def download_id(self) -> str:
        return self._dl_id

    def _filename(self) -> str:
        try:
            from urllib.parse import urlparse
            base = (urlparse(self._url).path or "").rsplit("/", 1)[-1]
            return base or "download"
        except Exception:
            return "download"

    def compose(self) -> ComposeResult:
        accent = _accent_color()
        title = Text()
        title.append("⬇ ", style=accent)
        title.append(self._filename(), style=f"bold {accent}")
        yield Static(title, id="dl-header", classes="dl-header")
        yield Static(Text(self._url, style="#6B7280"), id="dl-url",
                     classes="dl-url")
        yield Static(Text(_make_bar(0.0) + "  0%", style="#E5E7EB"),
                     id="dl-bar", classes="dl-bar")
        yield Static(Text("ожидание…", style="#9CA3AF"),
                     id="dl-stats", classes="dl-stats")
        yield Horizontal(
            Button("✕ Отменить", id=f"dl-cancel-{self._dl_id}",
                   classes="dl-cancel"),
            id="dl-btn-row", classes="dl-buttons",
        )

    def update_progress(self, *, received: int, total: int, elapsed: float,
                        done: bool, error: str = "") -> None:
        self._received = int(received)
        self._total = int(total)
        self._elapsed = float(elapsed)
        self._done = bool(done)
        self._error = str(error or "")

        percent = (100.0 * self._received / self._total) if self._total else 0.0
        bar_line = Text()
        bar_line.append(_make_bar(percent), style=_accent_color())
        if self._total:
            bar_line.append(f"  {percent:5.1f}%", style="#E5E7EB")
        else:
            bar_line.append(f"  {_humansize(self._received)}", style="#E5E7EB")

        speed = self._received / self._elapsed if self._elapsed > 0 else 0.0
        stats = Text()
        if self._total:
            stats.append(
                f"{_humansize(self._received)} / {_humansize(self._total)}",
                style="#E5E7EB",
            )
        else:
            stats.append(_humansize(self._received), style="#E5E7EB")
        stats.append(f"  ·  {_humansize(speed)}/s", style="#9CA3AF")
        stats.append(f"  ·  ⏱ {_format_elapsed(self._elapsed)}",
                     style="#9CA3AF")

        try:
            self.query_one("#dl-bar", Static).update(bar_line)
            self.query_one("#dl-stats", Static).update(stats)
        except Exception:
            pass

        if done:
            self._finalize()

    def _finalize(self) -> None:
        try:
            row = self.query_one("#dl-btn-row", Horizontal)
            row.remove()
        except Exception:
            pass

        if self._error:
            note = Text()
            note.append("✗ ", style="#EF4444")
            note.append(self._error, style="#EF4444")
        else:
            note = Text()
            note.append("✓ загрузка завершена", style="#10B981")
        try:
            self.mount(Static(note))
        except Exception:
            pass
