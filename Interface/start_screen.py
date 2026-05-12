"""Initial TUI screen for selecting a project before launching the main app."""
from __future__ import annotations

from collections import deque
from math import cos, sin
from pathlib import Path
from typing import Deque, Dict, Optional, Tuple

from rich.style import Style
from rich.text import Text
from rich.align import Align
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DirectoryTree, Input, Label, Static

from Agent.runtime_paths import recent_projects_json_path
from Interface.branding import APP_DISPLAY_NAME, APP_FULL_VERSION_LABEL
from Interface.ui_prefs import load_prefs

Point = Tuple[float, float, float]
RECENTS_PATH = recent_projects_json_path()
MAX_RECENTS = 5


def _build_logo_block() -> Text:
    """Текстовый логотип стартового экрана (figlet), градиент в фирменных фиолетовых."""
    try:
        from pyfiglet import figlet_format
        raw = figlet_format(APP_DISPLAY_NAME, font="colossal").rstrip("\n")
    except Exception:
        raw = (
            "██╗     ██████╗ ██████╗ ███╗   ██╗███████╗\n"
            "██║    ██╔═══██╗██╔══██╗████╗  ██║██╔════╝\n"
            "██║    ██║   ██║██████╔╝██╔██╗ ██║█████╗  \n"
            "██║    ██║   ██║██╔══██╗██║╚██╗██║██╔══╝  \n"
            "███████╗╚██████╔╝██║  ██║██║ ╚████║███████╗\n"
            "╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝"
        )

    colors = [
        "#2a0040",
        "#4a0070",
        "#6a00a8",
        "#8c2be2",
        "#a94cff",
        "#c77dff",
        "#d9a3ff",
        "#f5e6ff",
    ]
    out = Text()
    lines = raw.splitlines()
    total = max(1, len(lines) - 1)
    for idx, line in enumerate(lines):
        color_idx = int((idx / total) * (len(colors) - 1))
        out.append(line + "\n", style=Style(color=colors[color_idx], bold=True))
    return out


def load_recent_projects() -> list[Path]:
    try:
        import json

        if not RECENTS_PATH.exists():
            return []
        raw = json.loads(RECENTS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        out: list[Path] = []
        for item in raw:
            p = Path(str(item)).expanduser().resolve()
            if p.is_dir() and p not in out:
                out.append(p)
        return out[:MAX_RECENTS]
    except Exception:
        return []


def save_recent_project(path: Path) -> None:
    try:
        import json

        p = path.resolve()
        current = load_recent_projects()
        deduped = [x for x in current if x != p]
        new_list = [p] + deduped
        RECENTS_PATH.write_text(
            json.dumps([str(x) for x in new_list[:MAX_RECENTS]], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


class LorenzWidget(Widget):
    """Анимированный странный аттрактор (фиолетовая палитра), фон слева на стартовом экране."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.points: Deque[Point] = deque(maxlen=3200)
        self.x = 0.1
        self.y = 0.0
        self.z = 0.0
        self.angle = 0.0
        self.paused = False
        for _ in range(1500):
            self._step(0.01)

    def _step(self, dt: float) -> None:
        sigma = 10.0
        rho = 28.0
        beta = 8.0 / 3.0

        dx = sigma * (self.y - self.x)
        dy = self.x * (rho - self.z) - self.y
        dz = self.x * self.y - beta * self.z

        self.x += dx * dt
        self.y += dy * dt
        self.z += dz * dt
        self.points.append((self.x, self.y, self.z))

    def advance(self, steps: int = 24) -> None:
        for _ in range(steps):
            self._step(0.0085)
        self.angle += 0.0045

    def render(self) -> Text:
        width = max(20, self.size.width)
        height = max(10, self.size.height)
        cols = max(20, width - 1)
        rows = max(10, height - 1)
        grid = [[0.0] * cols for _ in range(rows)]

        pts = list(self.points)[-1600:]
        if not pts:
            return Text(" ")

        ca = cos(self.angle)
        sa = sin(self.angle)
        cb = cos(self.angle * 0.7)
        sb = sin(self.angle * 0.7)

        projected = []
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")

        for x, y, z in pts:
            x1 = x * ca + z * sa
            z1 = -x * sa + z * ca
            y1 = y * cb - z1 * sb
            x2 = -y1
            y2 = x1
            projected.append((x2, y2))
            if x2 < min_x:
                min_x = x2
            if x2 > max_x:
                max_x = x2
            if y2 < min_y:
                min_y = y2
            if y2 > max_y:
                max_y = y2

        span_x = (max_x - min_x) or 1e-6
        span_y = (max_y - min_y) or 1e-6
        scale = min((cols - 2) / span_x, (rows - 2) / span_y) * 0.95
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        n = len(projected)

        for i, (x, y) in enumerate(projected):
            px = int((x - cx) * scale + cols / 2)
            py = int((y - cy) * scale + rows / 2)
            if 0 <= px < cols and 0 <= py < rows:
                age = i / n
                intensity = age**1.6
                if intensity > grid[py][px]:
                    grid[py][px] = intensity

        chars = " .:-=+*#%@"
        colors = [
            "#14001f",
            "#2a0040",
            "#4a0070",
            "#6a00a8",
            "#8c2be2",
            "#a94cff",
            "#c77dff",
            "#d9a3ff",
            "#e6c7ff",
            "#f5e6ff",
        ]

        out = Text()
        levels = len(chars) - 1
        for y in range(rows):
            for x in range(cols):
                v = grid[y][x]
                if v <= 0:
                    out.append(" ")
                    continue
                idx = int(v * levels)
                if idx > levels:
                    idx = levels
                out.append(chars[idx], Style(color=colors[idx]))
            out.append(" " * (width - cols))
            out.append("\n")
        return out


class ProjectPickerScreen(ModalScreen[Optional[Path]]):
    """Pick a project directory with a tree."""

    from Interface.modal_style import MODAL_SHARED_CSS as _SHARED_CSS

    DEFAULT_CSS = _SHARED_CSS + """
    ProjectPickerScreen { align: center middle; }
    #picker {
        width: 92%;
        height: 92%;
    }
    #picker-title { height: auto; }
    #picker-nav { height: 3; layout: horizontal; margin: 0 0 1 0; }
    #picker-nav Button {
        min-width: 11;
        margin: 0 1 0 0;
        height: 3;
    }
    #picker-path {
        width: 1fr;
        background: #0D0D0D;
        color: #E5E7EB;
        border: solid #2D2D3D;
    }
    #picker-tree {
        height: 1fr;
        background: #12121A;
        border: solid #2D2D3D;
    }
    #picker-actions { height: 3; layout: horizontal; margin: 1 0 0 0; }
    #picker-actions Button {
        min-width: 16;
        margin: 0 1 0 0;
        height: 3;
    }
    """

    def __init__(self, start_dir: Path):
        super().__init__()
        self._start_dir = start_dir.resolve()
        self._selected_dir = start_dir
        self._root = Path("/")

    def compose(self) -> ComposeResult:
        with Vertical(id="picker", classes="modal-card"):
            yield Label("Выберите папку проекта", id="picker-title", classes="modal-title")
            with Horizontal(id="picker-nav"):
                yield Button("Root", id="picker-root")
                yield Button("Home", id="picker-home")
                yield Button("Up", id="picker-up")
                yield Button("CWD", id="picker-cwd")
                yield Input(str(self._start_dir), id="picker-path")
            yield DirectoryTree(str(self._root), id="picker-tree")
            with Horizontal(id="picker-actions"):
                yield Button("Открыть", id="picker-open", variant="primary")
                yield Button("Отмена", id="picker-cancel")

    def on_mount(self) -> None:
        try:
            from Interface.modal_style import apply_accent_to
            apply_accent_to(
                self,
                container_id="picker",
                title_id="picker-title",
                title_text="Выберите папку проекта",
            )
        except Exception:
            pass
        self._go_to(self._start_dir)

    def _go_to(self, target: Path) -> None:
        try:
            target = target.expanduser().resolve()
            if not target.exists():
                return
            if target.is_file():
                target = target.parent
            self._selected_dir = target
            tree = self.query_one("#picker-tree", DirectoryTree)
            try:
                tree.path = str(target)
                tree.root.expand()
            except Exception:
                tree.remove()
                container = self.query_one("#picker", Vertical)
                actions = self.query_one("#picker-actions", Horizontal)
                container.mount(DirectoryTree(str(target), id="picker-tree"), before=actions)
            self.query_one("#picker-path", Input).value = str(target)
        except Exception:
            pass

    @on(DirectoryTree.DirectorySelected, "#picker-tree")
    def on_dir(self, event: DirectoryTree.DirectorySelected) -> None:
        self._selected_dir = event.path
        self.query_one("#picker-path", Input).value = str(event.path)

    @on(DirectoryTree.FileSelected, "#picker-tree")
    def on_file(self, event: DirectoryTree.FileSelected) -> None:
        self._selected_dir = event.path.parent

    @on(Button.Pressed, "#picker-open")
    def on_open(self) -> None:
        self.dismiss(self._selected_dir)

    @on(Button.Pressed, "#picker-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#picker-root")
    def on_root(self) -> None:
        self._go_to(Path("/"))

    @on(Button.Pressed, "#picker-home")
    def on_home(self) -> None:
        self._go_to(Path.home())

    @on(Button.Pressed, "#picker-up")
    def on_up(self) -> None:
        self._go_to(self._selected_dir.parent)

    @on(Button.Pressed, "#picker-cwd")
    def on_cwd(self) -> None:
        self._go_to(self._start_dir)

    @on(Input.Submitted, "#picker-path")
    def on_path_submit(self, event: Input.Submitted) -> None:
        value = (event.value or "").strip()
        if value:
            self._go_to(Path(value).expanduser())


class StartScreenApp(App[Optional[Path]]):
    CSS = """
    Screen { layout: horizontal; }
    #left-pane { width: 1fr; height: 100%; border-right: solid #00000000; }
    #right-pane { width: 1fr; height: 100%; padding: 1 2; }
    #logo-header {
        width: 100%;
        height: auto;
        layout: horizontal;
        align: center bottom;
    }
    #logo {
        width: 1fr;
        height: auto;
        margin: 0 0 1 0;
        text-style: bold;
        color: #e5e7eb;
        text-align: center;
        background: transparent;
        border: none;
    }
    #app-version-badge {
        color: #64748b;
        text-style: none;
        margin: 0 0 2 1;
        height: auto;
    }
    #buttons { height: auto; }
    #buttons Button { width: 100%; margin: 0 0 1 0; }
    #recent-title { margin: 1 0 0 0; color: #94a3b8; }
    #recent-list {
        height: 1fr;
        border: round #2D2D3D33;
        background: transparent;
        padding: 0 1;
    }
    .recent-btn {
        width: 100%;
        margin: 0 0 1 0;
        background: transparent;
        border: round #2D2D3D55;
        color: $text;
        content-align: left middle;
    }
    .recent-btn:hover {
        background: #8B5CF622;
        border: round #8B5CF688;
    }
    """

    BINDINGS = [("q", "quit", "Quit"), ("escape", "quit", "Quit")]

    def __init__(self, cwd: Path):
        super().__init__()
        self._cwd = cwd.resolve()
        self._recent_map: Dict[str, Path] = {}

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="left-pane"):
                yield LorenzWidget(id="lorenz")
            with Vertical(id="right-pane"):
                with Horizontal(id="logo-header"):
                    yield Static(Align.center(_build_logo_block()), id="logo")
                    yield Label(APP_FULL_VERSION_LABEL, id="app-version-badge")
                with Vertical(id="buttons"):
                    yield Button("Открыть проект", id="btn-open-project")
                    yield Button("Открыть с текущей директории", id="btn-open-current")
                yield Label("Последние проекты", id="recent-title")
                yield VerticalScroll(id="recent-list")

    def on_mount(self) -> None:
        self._apply_theme()
        self._fill_recents()
        self.set_interval(1 / 10, self._tick)

    def _apply_theme(self) -> None:
        prefs = load_prefs()
        theme_name = str(prefs.get("theme", "Purple Dark")).lower()
        light_theme = "light" in theme_name
        if light_theme:
            bg = "#f8fafc"
            fg = "#1e293b"
            panel = "#00000000"
            muted = "#64748b"
        else:
            bg = "#0d0d0d"
            fg = "#e5e7eb"
            panel = "#00000000"
            muted = "#94a3b8"
        self.screen.styles.background = bg
        self.screen.styles.color = fg
        for selector, widget_cls, color in (
            ("#logo", Static, fg),
            ("#app-version-badge", Label, "#64748b"),
            ("#recent-title", Label, muted),
        ):
            try:
                self.query_one(selector, widget_cls).styles.color = color
            except Exception:
                pass
        try:
            self.query_one("#left-pane", Vertical).styles.border_right = ("solid", panel)
        except Exception:
            pass

    def _fill_recents(self) -> None:
        box = self.query_one("#recent-list", VerticalScroll)
        box.remove_children()
        self._recent_map.clear()
        recents = load_recent_projects()
        if not recents:
            box.mount(Label("Нет последних проектов"))
            return
        for idx, p in enumerate(recents[:MAX_RECENTS]):
            proj_name = p.name or str(p)
            path_str = str(p)
            if len(path_str) > 42:
                path_str = "..." + path_str[-39:]
            if len(proj_name) > 20:
                proj_name = proj_name[:17] + "..."
            spaces = " " * max(2, 24 - len(proj_name))
            label = f"{proj_name}{spaces}[dim]{path_str}[/dim]"
            btn_id = f"recent-{idx}"
            self._recent_map[btn_id] = p
            box.mount(Button(label, id=btn_id, classes="recent-btn"))

    def _finish(self, path: Optional[Path]) -> None:
        if path and path.is_dir():
            save_recent_project(path)
            self.exit(path.resolve())
            return
        self.exit(None)

    def _tick(self) -> None:
        """Периодически обновляет аттрактор слева (шаг симуляции перед перерисовкой)."""
        lorenz = self.query_one("#lorenz", LorenzWidget)
        if not lorenz.paused:
            lorenz.advance(24)
            lorenz.refresh()

    @on(Button.Pressed, "#btn-open-current")
    def open_current(self) -> None:
        self._finish(self._cwd)

    @on(Button.Pressed, "#btn-open-project")
    def open_project(self) -> None:
        self.push_screen(ProjectPickerScreen(self._cwd), self._on_project_picked)

    def _on_project_picked(self, picked: Optional[Path]) -> None:
        if picked:
            self._finish(picked)

    @on(Button.Pressed, ".recent-btn")
    def on_recent_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        target = self._recent_map.get(btn_id)
        if target:
            self._finish(target)


def select_project_path(cwd: Path) -> Optional[Path]:
    return StartScreenApp(cwd).run()

