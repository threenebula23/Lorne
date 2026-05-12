"""
Graph Display — Rich-визуализация работы параллельных агентов Creator Mode.

Отображает ASCII/Rich-граф с воркерами и их статусами в реальном времени.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, TYPE_CHECKING

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.columns import Columns
    from rich.layout import Layout
    from rich.live import Live
    from rich import box

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ANSI fallback
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
BLUE = "\033[34m"

# Статус-иконки
_STATUS_ICONS = {
    "idle": ("○", "dim"),
    "planning": ("📋", "yellow"),
    "working": ("▶", "cyan"),
    "done": ("✓", "green"),
    "error": ("✗", "red"),
    "waiting": ("⏳", "yellow"),
}

# Блокировка терминала для пользовательского ввода в параллельном режиме
TERMINAL_LOCK = threading.RLock()
_active_live: Optional[Any] = None

@contextmanager
def pause_live_display():
    """Пауза Live-отображения для ввода (с блокировкой)."""
    with TERMINAL_LOCK:
        global _active_live
        if _active_live is not None and getattr(_active_live, "is_started", False):
            try:
                _active_live.stop()
                yield
            finally:
                _active_live.start()
        else:
            yield


class WorkerInfo:
    """Информация о воркере для отображения."""

    def __init__(
        self,
        worker_id: str,
        task: str = "",
        model_type: str = "local",
        model_name: str = "",
        status: str = "idle",
    ):
        self.worker_id = worker_id
        self.task = task
        self.model_type = model_type  # "local" или "heavy"
        self.model_name = model_name
        self.status = status
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.result_preview: str = ""
        self.tool_calls: int = 0
        self.rounds: int = 0
        self.current_action: str = ""  # Мысли/задачи агента в реальном времени

    @property
    def elapsed(self) -> float:
        if self.start_time == 0:
            return 0
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time

    @property
    def elapsed_str(self) -> str:
        e = self.elapsed
        if e == 0:
            return ""
        if e < 60:
            return f"{e:.1f}s"
        return f"{e / 60:.1f}m"


def _make_worker_panel_rich(w: WorkerInfo) -> Panel:
    """Создать Rich Panel для одного воркера."""
    icon, color = _STATUS_ICONS.get(w.status, ("●", "white"))

    # Заголовок (Text + styles, не сырой markup — иначе видно «[magenta][HEAVY]»).
    model_tag = "LOCAL" if w.model_type == "local" else "HEAVY"
    model_color = "cyan" if w.model_type == "local" else "magenta"
    title = Text()
    title.append(" ", style="")
    title.append(f"{w.worker_id} ", style="bold")
    title.append("[", style="dim")
    title.append(model_tag, style=f"bold {model_color}")
    title.append("]", style="dim")

    # Тело
    lines: list[str] = []
    lines.append(f"[{color}]{icon}[/{color}] [{color}]{w.status.upper()}[/{color}]")

    task_short = w.task[:50] + "…" if len(w.task) > 50 else w.task
    lines.append(f"[dim]Задача:[/dim] {task_short}")

    if w.current_action and w.status == "working":
        # Убираем лишние переносы из мысли агента
        action_clean = " ".join(w.current_action.split())
        action_short = action_clean[:60] + "…" if len(action_clean) > 60 else action_clean
        lines.append(f"[dim]Мысли:[/dim] [italic]{action_short}[/italic]")

    if w.model_name:
        lines.append(f"[dim]Модель:[/dim] {w.model_name}")

    if w.elapsed > 0:
        lines.append(f"[dim]Время:[/dim] {w.elapsed_str}")

    if w.tool_calls > 0:
        lines.append(f"[dim]Вызовов:[/dim] {w.tool_calls}")

    if w.result_preview and w.status != "working":
        preview = w.result_preview[:80] + "…" if len(w.result_preview) > 80 else w.result_preview
        lines.append(f"[dim]Результат:[/dim] {preview}")

    body = "\n".join(lines)

    border = {
        "idle": "dim",
        "planning": "yellow",
        "working": "cyan",
        "done": "green",
        "error": "red",
        "waiting": "yellow",
    }.get(w.status, "white")

    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=border,
        box=box.ROUNDED,
        padding=(0, 1),
        width=40,
    )


def _make_worker_ascii(w: WorkerInfo) -> str:
    """Создать ASCII-представление воркера."""
    icon, _ = _STATUS_ICONS.get(w.status, ("●", ""))
    model_tag = "[LOCAL]" if w.model_type == "local" else "[HEAVY]"
    task_short = w.task[:35] + "…" if len(w.task) > 35 else w.task
    elapsed = f" {w.elapsed_str}" if w.elapsed > 0 else ""

    lines = [
        f"┌─ {w.worker_id} {model_tag} ───┐",
        f"│ {icon} {w.status.upper():<12}{elapsed:>8} │",
        f"│ {task_short:<30} │",
    ]
    if w.model_name:
        lines.append(f"│ {w.model_name:<30} │")
    lines.append(f"└{'─' * 32}┘")
    return "\n".join(lines)


def build_graph_renderable(
    workers: List[WorkerInfo],
    main_task: str = "",
    phase: str = "working",
) -> Any:
    """Построить Rich-рендеринг графа агентов.

    Returns:
        Panel с визуализацией (для использования в Live)
    """
    if not HAS_RICH:
        return _build_graph_ascii(workers, main_task, phase)

    # Счётчики
    done_count = sum(1 for w in workers if w.status == "done")
    error_count = sum(1 for w in workers if w.status == "error")
    working_count = sum(1 for w in workers if w.status == "working")
    total = len(workers)

    # Заголовок оркестратора
    phase_icon = {"planning": "📋", "working": "⚡", "done": "✓", "error": "✗"}.get(phase, "●")
    task_short = main_task[:70] + "…" if len(main_task) > 70 else main_task

    header_lines = [
        f"[bold]{phase_icon} Creator Mode[/bold]  [dim]{task_short}[/dim]",
        f"[dim]Воркеры:[/dim] {done_count}[green]✓[/green] {working_count}[cyan]▶[/cyan] {error_count}[red]✗[/red] / {total} всего",
    ]
    header = "\n".join(header_lines)

    # Панели воркеров
    worker_panels = [_make_worker_panel_rich(w) for w in workers]

    # Расположить в сетку (2 столбца)
    from rich.columns import Columns as RichColumns
    grid = RichColumns(worker_panels, equal=False, padding=(1, 2))

    # Финальная обёртка
    content = Text()
    content.append(header)

    from rich.console import Group
    body = Group(
        Text.from_markup(header),
        Text(""),
        grid,
    )

    border_color = {
        "planning": "yellow",
        "working": "blue",
        "done": "green",
        "error": "red",
    }.get(phase, "blue")

    return Panel(
        body,
        title="[bold white]⚡ Creator Orchestrator[/bold white]",
        title_align="left",
        border_style=border_color,
        box=box.DOUBLE,
        padding=(1, 2),
    )


def _build_graph_ascii(
    workers: List[WorkerInfo],
    main_task: str = "",
    phase: str = "working",
) -> str:
    """Построить ASCII-граф (fallback)."""
    lines = [
        "╔═══════════════ Creator Orchestrator ═══════════════╗",
        f"║ Задача: {main_task[:45]:<45} ║",
    ]

    done = sum(1 for w in workers if w.status == "done")
    total = len(workers)
    lines.append(f"║ Прогресс: {done}/{total} ║")
    lines.append("╠═══════════════════════════════════════════════════╣")

    for w in workers:
        lines.append(f"║ {_make_worker_ascii(w)}")

    lines.append("╚═══════════════════════════════════════════════════╝")
    return "\n".join(lines)


def _worker_fingerprint(w: WorkerInfo) -> tuple:
    """Стабильная подпись воркера без «тикающих» полей (elapsed)."""
    return (
        w.worker_id,
        w.status,
        w.task,
        w.model_name,
        w.model_type,
        w.tool_calls,
        w.rounds,
        w.current_action,
        w.result_preview,
    )


class GraphLiveDisplay:
    """Менеджер real-time отображения графа агентов через Rich Live."""

    def __init__(self, main_task: str = ""):
        self.main_task = main_task
        self.workers: List[WorkerInfo] = []
        self.phase = "planning"
        self._live: Optional[Any] = None
        self._console: Optional[Any] = None
        self._last_sig: Any = None

    def start(self) -> None:
        """Начать live-отображение."""
        if HAS_RICH:
            global _active_live
            from rich.console import Console
            self._console = Console()
            renderable = build_graph_renderable(self.workers, self.main_task, self.phase)
            self._live = Live(
                renderable,
                console=self._console,
                auto_refresh=False,
                refresh_per_second=2,
                transient=False,
            )
            self._live.start(refresh=True)
            _active_live = self._live
        else:
            print(_build_graph_ascii(self.workers, self.main_task, self.phase))

    def update(self) -> None:
        """Обновить отображение (только при смене данных воркеров, без таймера)."""
        if self._live and HAS_RICH:
            sig = (
                self.phase,
                self.main_task,
                tuple(_worker_fingerprint(w) for w in self.workers),
            )
            if sig == self._last_sig:
                return
            self._last_sig = sig
            renderable = build_graph_renderable(
                self.workers, self.main_task, self.phase,
            )
            self._live.update(renderable, refresh=True)
        elif not HAS_RICH:
            # ANSI: очистить и перерисовать
            import sys
            sys.stdout.write("\033[2J\033[H")
            print(_build_graph_ascii(self.workers, self.main_task, self.phase))

    def stop(self) -> None:
        """Остановить live-отображение."""
        global _active_live
        if self._live:
            self._live.stop()
            self._live = None
        _active_live = None

    def add_worker(self, worker: WorkerInfo) -> None:
        """Добавить воркера."""
        self.workers.append(worker)
        self.update()

    def update_worker(self, worker_id: str, **kwargs: Any) -> None:
        """Обновить состояние воркера."""
        for w in self.workers:
            if w.worker_id == worker_id:
                for k, v in kwargs.items():
                    if hasattr(w, k):
                        setattr(w, k, v)
                break
        self.update()

    def set_phase(self, phase: str) -> None:
        """Обновить фазу оркестратора."""
        self.phase = phase
        self.update()


def display_creator_result(workers: List[WorkerInfo], main_task: str, elapsed: float) -> None:
    """Показать финальный результат Creator Mode."""
    if HAS_RICH:
        from rich.console import Console
        console = Console()

        table = Table(
            title="[bold]⚡ Creator Mode — Результат[/bold]",
            box=box.ROUNDED,
            border_style="green",
            padding=(0, 1),
        )
        table.add_column("#", style="bold", width=3)
        table.add_column("Задача", min_width=30)
        table.add_column("Модель", style="dim")
        table.add_column("Тип", width=7)
        table.add_column("Статус", width=8)
        table.add_column("Время", justify="right", style="dim")
        table.add_column("Вызовов", justify="right", style="dim")

        for i, w in enumerate(workers, 1):
            icon, color = _STATUS_ICONS.get(w.status, ("●", "white"))
            task_short = w.task[:40] + "…" if len(w.task) > 40 else w.task
            status_str = f"[{color}]{icon} {w.status}[/{color}]"
            type_color = "cyan" if w.model_type == "local" else "magenta"
            type_str = f"[{type_color}]{w.model_type.upper()}[/{type_color}]"

            table.add_row(
                str(i),
                task_short,
                w.model_name,
                type_str,
                status_str,
                w.elapsed_str,
                str(w.tool_calls),
            )

        console.print()
        console.print(table)

        done = sum(1 for w in workers if w.status == "done")
        errors = sum(1 for w in workers if w.status == "error")
        local_count = sum(1 for w in workers if w.model_type == "local")
        heavy_count = sum(1 for w in workers if w.model_type == "heavy")

        console.print(
            f"\n  [bold]Итого:[/bold] {done}✓ выполнено, {errors}✗ ошибок  |  "
            f"{local_count} local, {heavy_count} heavy  |  {elapsed:.1f}s\n"
        )
    else:
        print(f"\n{'═' * 50}")
        print(f"Creator Mode — Результат")
        print(f"Задача: {main_task}")
        for i, w in enumerate(workers, 1):
            icon, _ = _STATUS_ICONS.get(w.status, ("●", ""))
            print(f"  {i}. {icon} [{w.model_type.upper()}] {w.task[:50]}  ({w.elapsed_str})")
        print(f"Общее время: {elapsed:.1f}s")
        print(f"{'═' * 50}\n")
