"""Thread-local slug режима чата на время ``agent_graph.stream`` (TUI / classic)."""

from __future__ import annotations

import threading

_tl = threading.local()


def set_stream_chat_mode(mode: str | None) -> None:
    """Выставить режим для текущего потока; ``None`` — сброс."""
    if mode is None:
        if hasattr(_tl, "value"):
            delattr(_tl, "value")
    else:
        _tl.value = str(mode).strip().lower() or "agent"


def get_stream_chat_mode() -> str:
    return getattr(_tl, "value", None) or "agent"
