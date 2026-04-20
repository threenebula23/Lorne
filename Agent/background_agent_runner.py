"""Short-lived background agent: LLM + tools in a worker thread (testing while main blocks)."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from Agent.message_utils import (
    coalesce_lc_response_tool_calls,
    coerce_assistant_content_to_text,
    extract_structured_tool_calls,
    extract_textual_tool_calls,
    normalize_tool_call,
    reconstruct_broken_content,
    sanitize_messages,
    extract_thought_segments,
    strip_think_tags,
    extract_inline_write_file_args,
)
from Agent.tool_schemas import validate_tool_arguments

_BG_SYSTEM = (
    "Ты — вспомогательный мини-агент TCA. У тебя одна краткая задача (тест, curl, "
    "pytest, проверка API, чтение логов). Работай только инструментами, без воды. "
    "Никаких ask_user. Заверши как можно быстрее. Если сервер ещё не готов — один "
    "короткий run_command (sleep + curl) или прочитай вывод. Результаты — факты из тулов."
)

_JOBS_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}


def _run_one_assistant_turn(
    llm_with_tools: Any,
    messages: List[Any],
) -> tuple[AIMessage, str]:
    raw = llm_with_tools.invoke(sanitize_messages(messages))
    content = coerce_assistant_content_to_text(getattr(raw, "content", ""))
    if isinstance(content, str):
        content = content.encode("utf-8", "ignore").decode("utf-8", "ignore")
    thought_segments, content = extract_thought_segments(content)
    for th in thought_segments:
        if (th or "").strip():
            try:
                from Interface.tui_bridge import get_bridge
                b = get_bridge()
                if b:
                    b.on_thought(f"[helper] {th.strip()[:2000]}")
            except Exception:
                pass
    content = strip_think_tags(content)
    meta = getattr(raw, "response_metadata", None) or {}
    merged = coalesce_lc_response_tool_calls(raw)
    if not merged:
        s = extract_structured_tool_calls(content, allow_implicit_write=False)
        if s:
            merged = s
            content = ""
        else:
            t, body = extract_textual_tool_calls(content)
            if t:
                merged = t
                content = body or ""
    if not merged and isinstance(content, str):
        inline = extract_inline_write_file_args(content)
        if inline is not None:
            merged = [
                {
                    "name": "write_file",
                    "args": inline,
                    "id": "call_bg_inline",
                    "type": "tool_call",
                }
            ]
            content = ""
    if not (content or "").strip() and thought_segments:
        content = thought_segments[-1]
    return AIMessage(content=content or "", tool_calls=merged or [], response_metadata=meta), content


def _execute_tool_block(
    tool_map: Dict[str, Any],
    last_ai: AIMessage,
) -> List[ToolMessage]:
    out: List[ToolMessage] = []
    for idx, tc in enumerate(last_ai.tool_calls or []):
        tc_n = normalize_tool_call(tc)
        name = str(tc_n.get("name", ""))
        args = reconstruct_broken_content(name, tc_n.get("args") or {})
        tid = str(tc_n.get("id") or f"bg_{idx}")
        args, err = validate_tool_arguments(name, args)
        if err:
            out.append(
                ToolMessage(
                    content=json.dumps({"error": "argument_validation", "detail": err}, ensure_ascii=False),
                    tool_call_id=tid,
                    name=name,
                )
            )
            continue
        t = tool_map.get(name)
        if t is None:
            out.append(
                ToolMessage(
                    content=json.dumps({"error": "unknown_tool", "tool": name}, ensure_ascii=False),
                    tool_call_id=tid,
                    name=name,
                )
            )
            continue
        t0 = time.time()
        try:
            res = t.invoke(args)
        except Exception as e:
            res = {"error": type(e).__name__, "detail": str(e)}
        if isinstance(res, dict) and "elapsed_seconds" not in res:
            res["elapsed_seconds"] = round(time.time() - t0, 3)
        try:
            from Interface.tui_bridge import get_bridge
            b = get_bridge()
            if b and name:
                b.on_tool_result(name, res)
        except Exception:
            pass
        body = res if isinstance(res, (dict, list)) else str(res)
        if isinstance(body, str):
            pass
        else:
            body = json.dumps(body, ensure_ascii=False, default=str)
        out.append(ToolMessage(content=body, tool_call_id=tid, name=name))
    return out


def run_short_agent_loop(
    task: str,
    tool_map: Dict[str, Any],
    llm_with_tools: Any,
    max_rounds: int = 12,
) -> str:
    """Synchronous mini-loop; used from worker thread."""
    messages: List[Any] = [
        SystemMessage(content=_BG_SYSTEM),
        HumanMessage(content=task),
    ]
    for _ in range(max(1, int(max_rounds))):
        ai, _ = _run_one_assistant_turn(llm_with_tools, messages)
        messages.append(ai)
        if not ai.tool_calls:
            text = (ai.content or "").strip()
            return text or "Helper finished without tool calls."
        t_msgs = _execute_tool_block(tool_map, ai)
        messages.extend(t_msgs)
    return "Helper: достигнут лимит раундов; последний ответ см. в истории тулов."


def start_background_job(
    task: str,
    tool_map: Dict[str, Any],
    llm_with_tools_factory,
    max_tool_rounds: int = 12,
) -> str:
    job_id = f"bg_{uuid.uuid4().hex[:12]}"
    ev = threading.Event()
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "status": "running",
            "result": None,
            "error": None,
            "event": ev,
            "started": time.time(),
        }

    def _worker() -> None:
        prev_ac = None
        try:
            from Agent.tools import terminal_tool as tt
            prev_ac = getattr(tt, "AUTO_CONFIRM", False)
            tt.AUTO_CONFIRM = True
        except Exception:
            tt = None  # type: ignore
        try:
            llm_wt = llm_with_tools_factory()
            summary = run_short_agent_loop(
                task, tool_map, llm_wt, max_rounds=max_tool_rounds,
            )
            with _JOBS_LOCK:
                if job_id in _JOBS:
                    _JOBS[job_id].update(
                        {"status": "done", "result": summary, "error": None}
                    )
                    _JOBS[job_id]["event"].set()
        except Exception as e:
            with _JOBS_LOCK:
                if job_id in _JOBS:
                    _JOBS[job_id].update(
                        {"status": "error", "result": None, "error": str(e)}
                    )
                    _JOBS[job_id]["event"].set()
        finally:
            if tt is not None:
                try:
                    tt.AUTO_CONFIRM = bool(prev_ac)
                except Exception:
                    pass

    threading.Thread(target=_worker, name=f"TCA-bg-{job_id}", daemon=True).start()
    return job_id


def get_job_status(job_id: str) -> Dict[str, Any]:
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return {"ok": False, "error": "unknown_job_id"}
        return {
            "ok": True,
            "status": j.get("status"),
            "result": j.get("result"),
            "error": j.get("error"),
        }


def wait_for_job(job_id: str, wait_seconds: float) -> Dict[str, Any]:
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return {"ok": False, "error": "unknown_job_id"}
        ev: threading.Event = j.get("event")  # type: ignore
    if not ev:
        return get_job_status(job_id)
    if wait_seconds and wait_seconds > 0:
        ev.wait(timeout=float(wait_seconds))
    return get_job_status(job_id)
