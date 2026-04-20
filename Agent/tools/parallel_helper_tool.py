"""Background helper: тот же пул тулов + отдельный LLM-цикл в потоке (тест, пока основной run_command ждёт)."""
from __future__ import annotations

import json
from typing import Any, Dict

from langchain_core.tools import tool

try:
    from ..background_agent_runner import start_background_job, wait_for_job, get_job_status
except ImportError:
    from Agent.background_agent_runner import start_background_job, wait_for_job, get_job_status


@tool
def start_background_task(
    task: str,
    max_tool_rounds: int = 12,
) -> Dict[str, Any]:
    """Запусти краткого **параллельного помощника** (отдельный LLM+инструменты в фоне).

    Используй, если основной поток скоро займёт `run_command` (сервер, долгий тест,
    сборка) и **параллельно** нужно: smoke-тест, `curl` к `localhost`, лёгкий `pytest`.

    Возвращает `job_id`. Затем `get_background_result(job_id, wait_seconds=...)`.
    """
    try:
        from Agent.tool_registry import build_tools, build_tool_map, bind_tools_safe, set_tool_session_prefs
        from Agent.llm_provider import get_llm
    except ImportError:
        from tool_registry import build_tools, build_tool_map, bind_tools_safe, set_tool_session_prefs
        from llm_provider import get_llm

    try:
        from Interface.ui_prefs import load_prefs
        prefs = load_prefs()
        am = False
        pw = bool(prefs.get("playwright_python_enabled", False))
        bw = bool(prefs.get("browser_tools_enabled", True))
    except Exception:
        am, pw, bw = False, False, True

    set_tool_session_prefs(agent_mode=am, playwright_python=pw, browser_tools=bw)
    tools, _ = build_tools(agent_mode=am, playwright_python=pw, browser_tools=bw)
    tmap = build_tool_map(tools)
    llm, _profile, mname = get_llm("fast")

    def _factory() -> Any:
        return bind_tools_safe(llm, mname, tools)

    job_id = start_background_job(
        str(task or "").strip(),
        tmap,
        _factory,
        max_tool_rounds=int(max_tool_rounds) if max_tool_rounds else 12,
    )
    return {
        "ok": True,
        "job_id": job_id,
        "hint": (
            "Помощник в фоне. Можно сразу вызвать длинный run_command. "
            "Итог: get_background_result(job_id, wait_seconds=...)."
        ),
    }


@tool
def get_background_result(job_id: str, wait_seconds: int = 0) -> Dict[str, Any]:
    """Статус или ожидание `start_background_task`. wait_seconds=0 — без ожидания."""
    jid = (job_id or "").strip()
    if not jid:
        return {"ok": False, "error": "job_id required"}
    if int(wait_seconds or 0) > 0:
        st = wait_for_job(jid, float(wait_seconds))
    else:
        st = get_job_status(jid)
    return st
