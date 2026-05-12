"""
Cross-platform command execution for Lorne.
Supports Windows (cmd.exe) and Unix (sh) with proper timeout and output handling.
"""
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

IS_WINDOWS = sys.platform == "win32"
DEFAULT_SHELL = "cmd.exe" if IS_WINDOWS else "/bin/sh"
SHELL_FLAG = "/c" if IS_WINDOWS else "-c"


def run_command(
    command: str,
    cwd: Optional[str] = None,
    timeout: Optional[int] = 120,
    env: Optional[dict] = None,
) -> Tuple[str, str, int]:
    """Execute a shell command. Returns (stdout, stderr, returncode)."""
    cwd_path = Path(cwd).resolve() if cwd else None
    run_kwargs = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "cwd": str(cwd_path) if cwd_path else None,
        "env": env,
        # Do not inherit stdin: scripts using input() or prompts would block on TTY.
        # DEVNULL yields immediate EOF on read so the process exits or errors; output still captured.
        "stdin": subprocess.DEVNULL,
    }
    if IS_WINDOWS:
        run_kwargs["shell"] = False
        proc = subprocess.run(
            [DEFAULT_SHELL, SHELL_FLAG, command],
            **{k: v for k, v in run_kwargs.items() if v is not None and k != "shell"},
        )
    else:
        run_kwargs["shell"] = True
        run_kwargs["executable"] = DEFAULT_SHELL
        proc = subprocess.run(command, **run_kwargs)

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if stdout and not stdout.endswith("\n"):
        stdout += "\n"
    if stderr and not stderr.endswith("\n"):
        stderr += "\n"
    return stdout, stderr, proc.returncode


def run_command_safe(
    command: str,
    cwd: Optional[str] = None,
    timeout: Optional[int] = 120,
    max_output_len: int = 64_000,
) -> dict:
    """Safe command execution for agent tools. Limits output length and catches errors."""
    try:
        stdout, stderr, returncode = run_command(command=command, cwd=cwd, timeout=timeout)
        if len(stdout) > max_output_len:
            stdout = stdout[:max_output_len] + "\n… [output truncated]\n"
        if len(stderr) > max_output_len:
            stderr = stderr[:max_output_len] + "\n… [output truncated]\n"
        return {"stdout": stdout, "stderr": stderr, "returncode": returncode}
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": (
                f"Command timed out after {timeout}s. "
                "If the program was waiting for input or a pager, use non-interactive flags or pipe answers; "
                "stdin is not connected to a TTY."
            ),
            "returncode": -1,
            "error": "TimeoutExpired",
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
            "error": type(e).__name__,
        }


def run_command_detached(
    command: str,
    cwd: Optional[str] = None,
    log_name: str = "background_cmd.log",
) -> Dict[str, Any]:
    """Start command in background; append stdout/stderr to каталог данных проекта (``.lorne`` / legacy ``.tca``) / ``<log_name>``.

    Use for long-running dev servers (``npm run dev``) so the agent is not blocked.
    """
    cwd_path = Path(cwd).resolve() if cwd else None
    try:
        from Agent.path_utils import get_project_root
        from Agent.runtime_paths import project_data_dir

        log_dir = project_data_dir(get_project_root())
    except Exception:
        from Agent.runtime_paths import project_data_dir

        log_dir = project_data_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    log_path = log_dir / log_name

    cwd_s = str(cwd_path) if cwd_path else None
    try:
        with open(log_path, "a", encoding="utf-8", errors="replace") as logf:
            logf.write(f"\n\n=== background: {command!r} cwd={cwd_s or 'default'} ===\n")
            logf.flush()
            if IS_WINDOWS:
                proc = subprocess.Popen(
                    [DEFAULT_SHELL, SHELL_FLAG, command],
                    cwd=cwd_s,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                )
            else:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    executable=DEFAULT_SHELL,
                    cwd=cwd_s,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
            "error": type(e).__name__,
            "background": False,
        }
    return {
        "stdout": f"Процесс запущен в фоне (pid={proc.pid}). Лог: {log_path}",
        "stderr": "",
        "returncode": 0,
        "background": True,
        "pid": proc.pid,
        "log_path": str(log_path),
    }
