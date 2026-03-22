"""Advanced input widget with @ file autocomplete and /command completion.

Uses prompt_toolkit for standalone mode and provides a Textual-compatible
autocomplete provider for the TUI app.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

# ─── Skip directories ──────────────────────────────────────────────
_SKIP_DIRS: Set[str] = {
    ".git", ".idea", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", ".DS_Store",
}

_COMMANDS = [
    "/help", "/exit", "/plan", "/status", "/profile", "/model",
    "/balance", "/credits", "/compact", "/versions", "/rollback",
    "/agent", "/custom", "/creator", "/ls", "/tree", "/rag",
    "/git status", "/git log", "/git diff", "/git rollback", "/git branch",
]

_COMMAND_HISTORY: List[str] = []
_MAX_HISTORY = 200


def add_to_history(text: str) -> None:
    text = text.strip()
    if not text or text.startswith("/exit"):
        return
    if _COMMAND_HISTORY and _COMMAND_HISTORY[-1] == text:
        return
    _COMMAND_HISTORY.append(text)
    if len(_COMMAND_HISTORY) > _MAX_HISTORY:
        _COMMAND_HISTORY.pop(0)


# ─── File scanning ─────────────────────────────────────────────────

def _scan_files(root: Optional[Path] = None, max_files: int = 500) -> List[str]:
    """Recursively scan project files for @ autocomplete."""
    root = root or Path.cwd()
    results: List[str] = []
    try:
        for item in sorted(root.rglob("*")):
            if len(results) >= max_files:
                break
            parts = item.relative_to(root).parts
            if any(p in _SKIP_DIRS or p.startswith(".") for p in parts):
                continue
            if item.is_file():
                results.append(str(item.relative_to(root)))
    except (PermissionError, OSError):
        pass
    return results


_cached_files: List[str] = []
_cache_root: Optional[str] = None


def get_project_files(root: Optional[Path] = None) -> List[str]:
    global _cached_files, _cache_root
    r = str(root or Path.cwd())
    if _cache_root != r or not _cached_files:
        _cached_files = _scan_files(Path(r))
        _cache_root = r
    return _cached_files


def invalidate_file_cache() -> None:
    global _cached_files, _cache_root
    _cached_files = []
    _cache_root = None


# ─── prompt_toolkit based input ────────────────────────────────────

def get_user_input_advanced(project_root: Optional[Path] = None) -> str:
    """Prompt with @ file completion, /command completion, and history."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.styles import Style
    except ImportError:
        return input("❯ ")

    class TCACompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            word = document.get_word_before_cursor(WORD=True)

            # @ file completion
            at_pos = text.rfind("@")
            if at_pos >= 0:
                after_at = text[at_pos + 1:]
                files = get_project_files(project_root)
                for f in files:
                    if after_at and not f.lower().startswith(after_at.lower()):
                        continue
                    yield Completion(
                        f,
                        start_position=-len(after_at),
                        display=f,
                        display_meta="file",
                    )
                return

            # /command completion
            if text.startswith("/"):
                for cmd in _COMMANDS:
                    if cmd.startswith(text.lower()):
                        yield Completion(
                            cmd,
                            start_position=-len(text),
                            display=cmd,
                            display_meta="command",
                        )
                return

    style = Style.from_dict({
        "prompt": "#8B5CF6 bold",
        "completion-menu": "bg:#1a1a2e #E5E7EB",
        "completion-menu.completion": "bg:#1a1a2e #E5E7EB",
        "completion-menu.completion.current": "bg:#8B5CF6 #ffffff",
        "completion-menu.meta.completion": "bg:#1a1a2e #6B7280",
        "completion-menu.meta.completion.current": "bg:#8B5CF6 #E5E7EB",
        "scrollbar.background": "bg:#1a1a2e",
        "scrollbar.button": "bg:#8B5CF6",
    })

    history = InMemoryHistory()
    for h in _COMMAND_HISTORY:
        history.append_string(h)

    session = PromptSession(
        completer=TCACompleter(),
        style=style,
        history=history,
        complete_while_typing=False,
        enable_history_search=True,
    )

    try:
        result = session.prompt([("class:prompt", "❯ ")])
        add_to_history(result)
        return result
    except (KeyboardInterrupt, EOFError):
        return "/exit"


# ─── Textual autocomplete provider ─────────────────────────────────

def get_file_suggestions(partial: str, max_results: int = 15) -> List[Dict[str, str]]:
    """Get file suggestions for @ trigger in Textual Input."""
    files = get_project_files()
    partial_lower = partial.lower()
    results = []
    for f in files:
        if partial_lower and not f.lower().startswith(partial_lower):
            if partial_lower not in f.lower():
                continue
        results.append({"value": f, "display": f})
        if len(results) >= max_results:
            break
    return results


def get_command_suggestions(partial: str) -> List[Dict[str, str]]:
    """Get command suggestions for / trigger in Textual Input."""
    partial_lower = partial.lower()
    return [
        {"value": cmd, "display": cmd}
        for cmd in _COMMANDS
        if cmd.startswith(partial_lower)
    ]
