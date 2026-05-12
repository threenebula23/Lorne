"""Slash-команды — пакет (раньше один ``command_router.py``)."""
from __future__ import annotations

from ._main import CommandRouter, _normalize_slash_command_input, _should_autoplan

__all__ = [
    "CommandRouter",
    "_normalize_slash_command_input",
    "_should_autoplan",
]
