"""Константы продукта Lorne: имя, версия, вспомогательные строки для UI и HTTP.

Пример:

    from Interface.branding import APP_DISPLAY_NAME, user_agent_fragment
    print(f"{APP_DISPLAY_NAME} {user_agent_fragment()}")
"""
from __future__ import annotations

APP_DISPLAY_NAME: str = "Lorne"
APP_VERSION: str = "0.98"
APP_FULL_VERSION_LABEL: str = f"v{APP_VERSION}"
APP_CLI_SUBTITLE: str = "Terminal coding assistant"

_STRANGE_ATTRACTOR_LINES: tuple[str, ...] = (
    "    ·   ",
    "   ··   ",
    "  ···   ",
    " ·····  ",
    "······· ",
    " ·····  ",
    "  ···   ",
)


def cli_attractor_block() -> str:
    """Статичный мини-блок слева от логотипа в classic CLI (палитра фиолетового TUI).

    Возвращает многострочную ASCII-«искру» без анимации — только визуальный якорь.

    Пример::

        from rich.text import Text
        from Interface.branding import cli_attractor_block
        print(Text(cli_attractor_block(), style=\"dim #6a00a8\"))
    """
    return "\n".join(_STRANGE_ATTRACTOR_LINES)


def user_agent_fragment() -> str:
    """Фрагмент User-Agent для исходящих HTTP-запросов (совместимость с логами серверов).

    Пример::

        headers = {\"User-Agent\": f\"Mozilla/5.0 (compatible; {user_agent_fragment()})\"}
    """
    return f"{APP_DISPLAY_NAME}/{APP_VERSION}"
