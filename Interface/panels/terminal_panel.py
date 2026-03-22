"""Terminal panel — embedded terminal emulator with tabs + close support."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any, Optional

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button, Input, Label, RichLog, Static,
    TabbedContent, TabPane,
)

try:
    from textual_terminal import Terminal as TextualTerminal
    HAS_TERMINAL = True
except (ImportError, Exception):
    HAS_TERMINAL = False


class _FallbackTerminal(Vertical):
    """Simple command runner used when textual-terminal is unavailable."""

    DEFAULT_CSS = """
    _FallbackTerminal { height: 1fr; }
    _FallbackTerminal RichLog { height: 1fr; background: #0D0D0D; }
    _FallbackTerminal Input { dock: bottom; background: #151520; color: #E5E7EB; border: solid #2D2D3D; }
    """

    def __init__(self, tab_id: str, **kwargs):
        super().__init__(**kwargs)
        self._tab_id = tab_id

    def compose(self) -> ComposeResult:
        yield RichLog(id=f"term-out-{self._tab_id}", wrap=True, markup=True)
        yield Input(placeholder="$ command…", id=f"term-in-{self._tab_id}")

    def on_mount(self) -> None:
        try:
            out = self.query_one(f"#term-out-{self._tab_id}", RichLog)
            out.write(f"[#6B7280]TCA Terminal (type commands below)[/]")
            out.write(f"[#6B7280]cwd: {Path.cwd()}[/]")
        except Exception:
            pass


class TerminalPanel(Vertical):
    """Center lower panel — terminal emulator with tabs + close."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tab_counter = 0
        self._terminals: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="term-tab-bar"):
            yield Button("+ New Tab", id="term-new-tab", variant="default")
        yield TabbedContent(id="term-tabs")

    def on_mount(self) -> None:
        self._add_terminal_tab()

    def _add_terminal_tab(self) -> None:
        self._tab_counter += 1
        tab_id = f"term-{self._tab_counter}"
        label = f"Terminal {self._tab_counter}"
        tabs = self.query_one("#term-tabs", TabbedContent)
        pane = TabPane(label, id=tab_id)
        tabs.add_pane(pane)

        close_btn = Button(
            f"✕ T{self._tab_counter}",
            id=f"term-close-{tab_id}",
            classes="term-close-btn",
        )
        bar = self.query_one("#term-tab-bar", Horizontal)
        bar.mount(close_btn)

        if HAS_TERMINAL:
            outer = Vertical(id=f"term-wrap-{tab_id}")
            pane.mount(outer)
            shell = _detect_shell()
            terminal = TextualTerminal(command=shell, id=f"tw-{self._tab_counter}")
            outer.mount(terminal)
            self._terminals[tab_id] = terminal
            try:
                terminal.start()
            except Exception:
                outer.mount(Label("  Terminal failed to start"))
            # RichLog for F5 / Run — real shell widget has no RichLog
            out = RichLog(
                id=f"term-out-{tab_id}",
                wrap=True,
                markup=True,
                classes="term-run-output",
            )
            outer.mount(out)
            try:
                out.write("[#6B7280]— Run output (F5 / Run) —[/]")
            except Exception:
                pass
        else:
            pane.mount(_FallbackTerminal(tab_id=tab_id))

        tabs.active = tab_id

    @on(Button.Pressed, "#term-new-tab")
    def on_new_tab(self) -> None:
        self._add_terminal_tab()

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("term-close-"):
            tab_id = btn_id.replace("term-close-", "")
            self._close_terminal_tab(tab_id, event.button)

    def _close_terminal_tab(self, tab_id: str, close_btn: Button) -> None:
        tabs = self.query_one("#term-tabs", TabbedContent)
        try:
            tabs.remove_pane(tab_id)
        except Exception:
            pass
        self._terminals.pop(tab_id, None)
        try:
            close_btn.remove()
        except Exception:
            pass

        remaining = list(tabs.query(TabPane))
        if not remaining:
            self._add_terminal_tab()

    def run_command(self, cmd: str) -> None:
        """Programmatically run a command in the active terminal tab."""
        tabs = self.query_one("#term-tabs", TabbedContent)
        active = tabs.active
        if active is not None and not isinstance(active, str):
            active = getattr(active, "id", None) or str(active)
        if not active:
            self._add_terminal_tab()
            active = f"term-{self._tab_counter}"

        try:
            output_widget = self.query_one(f"#term-out-{active}", RichLog)
        except Exception:
            # Fallback: any RichLog in this panel
            try:
                output_widget = self.query(RichLog)[-1]
            except Exception:
                return

        output_widget.write(f"[bold #8B5CF6]$ {cmd}[/]")

        def _run_in_thread():
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=60,
                    cwd=str(Path.cwd()),
                )
                self.app.call_from_thread(self._show_result, output_widget, result)
            except subprocess.TimeoutExpired:
                self.app.call_from_thread(
                    output_widget.write, "[bold #F59E0B]Command timed out (60s)[/]"
                )
            except Exception as e:
                self.app.call_from_thread(
                    output_widget.write, f"[bold #EF4444]Error: {e}[/]"
                )

        threading.Thread(target=_run_in_thread, daemon=True).start()

    @on(Input.Submitted)
    def on_fallback_command(self, event: Input.Submitted) -> None:
        inp_id = event.input.id or ""
        if not inp_id.startswith("term-in-"):
            return
        tab_id = inp_id.replace("term-in-", "")
        cmd = event.value.strip()
        event.input.value = ""
        if not cmd:
            return

        try:
            output_widget = self.query_one(f"#term-out-{tab_id}", RichLog)
        except Exception:
            return

        output_widget.write(f"[bold #8B5CF6]$ {cmd}[/]")

        def _run_in_thread():
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=30,
                    cwd=str(Path.cwd()),
                )
                self.app.call_from_thread(self._show_result, output_widget, result)
            except subprocess.TimeoutExpired:
                self.app.call_from_thread(
                    output_widget.write, "[bold #F59E0B]Command timed out (30s)[/]"
                )
            except Exception as e:
                self.app.call_from_thread(
                    output_widget.write, f"[bold #EF4444]Error: {e}[/]"
                )

        threading.Thread(target=_run_in_thread, daemon=True).start()

    def _show_result(self, output_widget: RichLog, result) -> None:
        if result.stdout:
            output_widget.write(result.stdout.rstrip())
        if result.stderr:
            output_widget.write(f"[bold #EF4444]{result.stderr.rstrip()}[/]")
        if result.returncode != 0:
            output_widget.write(f"[#6B7280]exit code: {result.returncode}[/]")


def _detect_shell() -> str:
    import os
    shell = os.environ.get("SHELL", "")
    if shell:
        return shell
    if Path("/bin/zsh").exists():
        return "/bin/zsh"
    if Path("/bin/bash").exists():
        return "/bin/bash"
    return "sh"
