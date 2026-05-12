"""Вспомогательные функции для блоков сообщений в чате."""
from __future__ import annotations

import re
from pathlib import Path

from ._constants import MARKDOWN_SYNTAX_THEME_MAP

def _split_thoughts_and_body(text: str) -> tuple[list[str], str]:
    """Извлекает блоки рассуждений (как в graph_runner / message_utils)."""
    try:
        from Agent.message_utils import extract_thought_segments
        return extract_thought_segments(text or "")
    except Exception:
        thoughts: list[str] = []

        def _sub(m: re.Match) -> str:
            inner = (m.group(1) or "").strip()
            if inner:
                thoughts.append(inner)
            return ""

        body = re.compile(r"<thought>([\s\S]*?)</thought>", re.IGNORECASE).sub(_sub, text or "")
        return thoughts, (body or "").strip()


def _format_path_for_chip(full_path: str, max_len: int = 58) -> str:
    """Readable parent path for context chips (middle truncation)."""
    try:
        p = Path(full_path).expanduser().resolve()
        s = str(p.parent)
    except Exception:
        s = str(Path(full_path).parent)
    s = s.replace("\n", " ")
    if len(s) <= max_len:
        return s
    keep = max_len - 1
    left = keep // 2
    right = keep - left
    return s[:left] + "…" + s[-right:]


def _syntax_theme() -> str:
    try:
        from Interface.ui_prefs import load_prefs
        pref = str(load_prefs().get("syntax_theme", "monokai"))
        return MARKDOWN_SYNTAX_THEME_MAP.get(pref, "monokai")
    except Exception:
        return "monokai"

