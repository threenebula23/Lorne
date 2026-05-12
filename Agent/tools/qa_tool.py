"""One-shot QA scripts (npm/pnpm) to catch build and framework errors before shipping."""
from __future__ import annotations

from typing import Any, Dict

from langchain_core.tools import tool


@tool
def run_package_script(
    script: str = "build",
    package_manager: str = "npm",
    cwd: str = "",
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    """npm|pnpm|yarn run <script> (default build) в cwd; для dev — run_command(background=True)."""
    from Terminal.runner import run_command_safe

    pm = (package_manager or "npm").strip().lower()
    if pm not in ("npm", "pnpm", "yarn"):
        return {"ok": False, "error": f"unsupported package_manager: {pm}"}

    if pm == "npm":
        cmd = f"npm run {script}"
    elif pm == "pnpm":
        cmd = f"pnpm run {script}"
    else:
        cmd = f"yarn run {script}"

    try:
        from Agent.path_utils import resolve_abs_path
    except ImportError:
        from ..path_utils import resolve_abs_path  # type: ignore

    cwd_str = None
    if (cwd or "").strip():
        p = resolve_abs_path(cwd)
        if p.is_dir():
            cwd_str = str(p)

    out = run_command_safe(command=cmd, cwd=cwd_str, timeout=timeout_seconds)
    if isinstance(out, dict):
        out.setdefault("script", script)
        out.setdefault("package_manager", pm)
        out["ok"] = out.get("returncode") == 0
    return out  # type: ignore[return-value]
