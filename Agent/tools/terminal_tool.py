"""Инструмент выполнения команд в терминале (Windows/Unix)."""
from __future__ import annotations

import time
from typing import Any, Dict

from langchain_core.tools import tool

try:
    from ..path_utils import resolve_abs_path
except ImportError:
    from pathlib import Path

    def resolve_abs_path(path_str: str) -> Path:
        p = Path(path_str).expanduser()
        return (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()

_PROJECT_ROOT = None
_RECENT: Dict[str, Dict[str, Any]] = {}

AUTO_CONFIRM = False


def _sig(command: str, cwd: str) -> str:
    return f"{(command or '').strip()}|{(cwd or '').strip()}"


def _too_soon(signature: str, window_s: int = 5) -> bool:
    obj = _RECENT.get(signature)
    if not obj:
        return False
    return (time.time() - float(obj.get("ts", 0))) < window_s


def _get_project_root():
    global _PROJECT_ROOT
    if _PROJECT_ROOT is None:
        import sys
        from pathlib import Path
        agent_root = Path(__file__).resolve().parent.parent
        _PROJECT_ROOT = agent_root.parent
        if str(_PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(_PROJECT_ROOT))
    return _PROJECT_ROOT


def _is_dangerous(command: str) -> bool:
    """Грубая проверка на явно разрушительные команды."""
    cmd = (command or "").lower().strip()
    dangerous_patterns = [
        "rm -rf",
        "rm -r",
        "rm -f /",
        "mkfs",
        ":(){ :|:& };:",
        "del /s",
        "format ",
    ]
    return any(pat in cmd for pat in dangerous_patterns)

@tool
def run_command(command: str, cwd: str = "", timeout_seconds: int = 30) -> Dict[str, Any]:
    """Выполняет команду в терминале (Windows: cmd, Unix: sh) ТОЛЬКО с подтверждением пользователя.
    stdin у процесса закрыт (неинтерактивный режим): программы с input() или ожиданием ввода получат EOF и завершатся или выдадут ошибку — используй неинтерактивные флаги, echo/pipe или другой способ.
    cwd — рабочая директория: пустая строка или '.' = текущая директория проекта. Если путь не существует — команда выполнится в текущей директории."""
    from pathlib import Path
    from Terminal.runner import run_command_safe
    
    try:
        from Interface.graph_display import pause_live_display
    except ImportError:
        from contextlib import contextmanager
        @contextmanager
        def pause_live_display():
            yield

    signature = _sig(command, cwd)
    if _too_soon(signature, window_s=20):
        return {
            "stdout": "",
            "stderr": "Команда пропущена: повтор того же запуска слишком скоро (защита от циклов).",
            "returncode": -3,
            "skipped": True,
            "reason": "duplicate_recent_command",
        }
    if _is_dangerous(command):
        return {
            "stdout": "",
            "stderr": "Команда заблокирована как потенциально разрушительная.",
            "returncode": -4,
            "skipped": True,
            "reason": "dangerous_command",
        }

    if AUTO_CONFIRM:
        ans = "y"
    else:
        from Interface.tui_bridge import get_bridge
        bridge = get_bridge()
        if bridge:
            confirmed = bridge.request_confirmation(
                f"Run command?",
                f"$ {command}"
            )
            ans = "y" if confirmed else "n"
        else:
            with pause_live_display():
                try:
                    import sys
                    if not sys.stdin.isatty():
                        ans = "eof"
                    else:
                        ans = input(f"  Разрешить выполнить команду?\n  $ {command}\n  [y/N] > ").strip().lower()
                except (EOFError, KeyboardInterrupt, RuntimeError):
                    ans = "eof"

    if ans == "eof":
        return {
            "stdout": "", 
            "stderr": "Terminal input unavailable (EOF or not a TTY). You cannot run interactive commands here. DO NOT RETRY THIS COMMAND. Please inform the user or proceed with alternative non-interactive tools (like write_file).", 
            "returncode": -2, 
            "skipped": True
        }
    elif ans not in ("y", "yes", "да", "д"):
        return {"stdout": "", "stderr": "Команда отменена пользователем. Пожалуйста, выбери другой путь решения.", "returncode": -2, "skipped": True}
    
    cwd_str = None
    if cwd.strip():
        resolved = resolve_abs_path(cwd)
        if resolved.exists() and resolved.is_dir():
            cwd_str = str(resolved)
        # иначе cwd_str остаётся None — выполнение в текущей директории
    
    res = run_command_safe(command=command.strip(), cwd=cwd_str, timeout=timeout_seconds)
    _RECENT[signature] = {"ts": time.time(), "returncode": res.get("returncode")}
    return res
