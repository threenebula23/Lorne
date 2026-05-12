"""Краткий splash при старте (Rich + pyfiglet) для Lorne."""
from __future__ import annotations

import sys


def show_splash(model_name: str = "", version: str = "") -> None:
    """Печатает баннер с именем продукта и версией (до поднятия Textual)."""
    try:
        from Interface.branding import APP_VERSION
        ver = version or APP_VERSION
    except ImportError:
        ver = version or "0.98"
    try:
        from pyfiglet import figlet_format
    except ImportError:
        _show_simple_splash(model_name, ver)
        return

    try:
        from rich.console import Console
        from rich.text import Text
        from rich.panel import Panel
        from rich import box
    except ImportError:
        _show_simple_splash(model_name, ver)
        return

    console = Console()
    try:
        from Interface.branding import APP_DISPLAY_NAME, APP_CLI_SUBTITLE
    except ImportError:
        APP_DISPLAY_NAME = "Lorne"
        APP_CLI_SUBTITLE = "Terminal coding assistant"

    logo = figlet_format(APP_DISPLAY_NAME, font="slant")
    logo_text = Text()
    for i, line in enumerate(logo.splitlines()):
        shade = max(80, 139 - i * 10)
        logo_text.append(line + "\n", style=f"bold rgb({shade},{shade // 2 + 40},{min(255, shade + 80)})")

    subtitle = Text()
    subtitle.append(f"  {APP_CLI_SUBTITLE}", style="bold #A78BFA")
    subtitle.append(f"  v{ver}\n", style="#6B7280")
    subtitle.append("  ─" * 20 + "\n", style="#2D2D3D")

    info = Text()
    if model_name:
        info.append(f"  Model: ", style="#6B7280")
        info.append(f"{model_name}\n", style="bold #8B5CF6")
    info.append("  Mode:  ", style="#6B7280")
    info.append("Textual TUI\n", style="#10B981")
    info.append("  Hint:  ", style="#6B7280")
    info.append("@file for autocomplete, /help for commands\n", style="#E5E7EB")

    content = Text()
    content.append_text(logo_text)
    content.append_text(subtitle)
    content.append_text(info)

    console.print(Panel(
        content,
        border_style="#2D2D3D",
        box=box.HEAVY,
        padding=(1, 2),
    ))
    console.print()


def _show_simple_splash(model_name: str = "", version: str = "0.98") -> None:
    """Fallback-баннер без Rich/pyfiglet."""
    purple = "\033[38;2;139;92;246m"
    gray = "\033[38;2;107;114;128m"
    reset = "\033[0m"
    bold = "\033[1m"
    try:
        from Interface.branding import APP_CLI_SUBTITLE, APP_DISPLAY_NAME
    except ImportError:
        APP_DISPLAY_NAME = "Lorne"
        APP_CLI_SUBTITLE = "Terminal coding assistant"

    print(f"""
{purple}{bold}  {APP_DISPLAY_NAME}{reset}

  {purple}{APP_CLI_SUBTITLE}{reset} {gray}v{version}{reset}
  {gray}Model: {purple}{model_name}{reset}
  {gray}@file for autocomplete, /help for commands{reset}
""")
