"""
Creator Mode — оркестратор параллельных агентов для TCA.

Разбивает сложную задачу на подзадачи и параллельно выполняет их
через ThreadPoolExecutor, используя маршрутизацию local/heavy моделей.
"""
from __future__ import annotations

import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph, MessagesState
from langchain_openai import ChatOpenAI

try:
    from .creator_provider import (
        get_local_llm, get_heavy_llm, classify_task_complexity,
        route_to_model, get_creator_config, check_local_server,
    )
    from .creator_orchestration import (
        normalize_orchestration,
        worker_roles_for_count,
        format_worker_mode_section,
        build_worker_user_content,
        synthesize_supervisor_report,
    )
    from .planner import build_plan
    from .system_promt import SYSTEM_PROMPT
except ImportError:
    from Agent.creator_provider import (
        get_local_llm, get_heavy_llm, classify_task_complexity,
        route_to_model, get_creator_config, check_local_server,
    )
    from Agent.creator_orchestration import (
        normalize_orchestration,
        worker_roles_for_count,
        format_worker_mode_section,
        build_worker_user_content,
        synthesize_supervisor_report,
    )
    from Agent.planner import build_plan
    from Agent.system_promt import SYSTEM_PROMPT

try:
    from .message_utils import (
        coalesce_lc_response_tool_calls,
        coerce_assistant_content_to_text,
        extract_textual_tool_calls,
        extract_structured_tool_calls,
        normalize_tool_call,
        summarize_tool_like_final_answer,
    )
except ImportError:
    from Agent.message_utils import (
        coalesce_lc_response_tool_calls,
        coerce_assistant_content_to_text,
        extract_textual_tool_calls,
        extract_structured_tool_calls,
        normalize_tool_call,
        summarize_tool_like_final_answer,
    )

try:
    from .tool_registry import bind_tools_safe
except ImportError:
    from Agent.tool_registry import bind_tools_safe

try:
    from .message_utils import reconstruct_broken_content
except ImportError:
    from Agent.message_utils import reconstruct_broken_content

try:
    from .tool_schemas import validate_tool_arguments
except ImportError:
    from Agent.tool_schemas import validate_tool_arguments

try:
    from Interface.graph_display import (
        WorkerInfo, GraphLiveDisplay, display_creator_result,
    )
    from Interface.visualization import display_file_diffs
except ImportError:
    WorkerInfo = None
    GraphLiveDisplay = None
    display_creator_result = None
    def display_file_diffs(f): pass


# ─── Worker Agent ───────────────────────────────────────────────────

_MAX_WORKER_ROUNDS = 100


class _AuthFallbackError(Exception):
    """Raised when a local model returns an auth error, triggering fallback to heavy."""
    pass


def _build_worker_graph(
    llm: ChatOpenAI,
    tools: List[BaseTool],
    model_name: str,
) -> Any:
    """Строит LangGraph для одного воркера."""

    tool_map: Dict[str, BaseTool] = {}
    for t in tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", None)
        if name:
            tool_map[str(name)] = t

    llm_with_tools = bind_tools_safe(llm, model_name, tools)

    def call_model(state: MessagesState) -> Dict[str, List[AIMessage]]:
        messages = state["messages"]
        try:
            response = llm_with_tools.invoke(messages)
        except Exception as e:
            return {"messages": [AIMessage(content=f"Ошибка: {e}")]}

        content = coerce_assistant_content_to_text(getattr(response, "content", ""))
        if isinstance(content, str):
            content = content.encode("utf-8", "ignore").decode("utf-8", "ignore")
        meta = getattr(response, "response_metadata", None) or {}

        merged = coalesce_lc_response_tool_calls(response)
        if merged:
            return {"messages": [AIMessage(
                content=content, tool_calls=merged, response_metadata=meta,
            )]}

        structured_tool_calls = extract_structured_tool_calls(content)
        if structured_tool_calls:
            return {"messages": [AIMessage(
                content="",
                tool_calls=structured_tool_calls,
                response_metadata=meta,
            )]}
        textual_tool_calls, body = extract_textual_tool_calls(content)
        if textual_tool_calls:
            return {"messages": [AIMessage(
                content=body or "", tool_calls=textual_tool_calls, response_metadata=meta,
            )]}
        if isinstance(content, str):
            recent_tool_ctx = any(isinstance(m, ToolMessage) for m in messages[-4:])
            if recent_tool_ctx:
                humanized = summarize_tool_like_final_answer(content)
                if humanized:
                    content = humanized
        return {"messages": [AIMessage(content=content, response_metadata=meta)]}

    def execute_tools(state: MessagesState) -> Dict[str, List[Any]]:
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        results = []
        for tc in tool_calls:
            tc_dict = normalize_tool_call(tc)
            tool_name = str(tc_dict.get("name", ""))
            tool_args = reconstruct_broken_content(tool_name, tc_dict.get("args", {}) or {})
            tool_call_id = str(tc_dict.get("id", f"call_{hash(tool_name)}"))

            tool_obj = tool_map.get(tool_name)
            _t_tool_start = time.time()
            if tool_obj is None:
                result = f"Unknown tool: {tool_name}"
            else:
                tool_args, val_err = validate_tool_arguments(tool_name, tool_args)
                if val_err:
                    result = {"error": "argument_validation", "detail": val_err}
                else:
                    try:
                        result = tool_obj.invoke(tool_args)
                    except Exception as e:
                        result = f"Error: {e}"
            if isinstance(result, dict) and "elapsed_seconds" not in result:
                result["elapsed_seconds"] = round(time.time() - _t_tool_start, 3)

            # Propagate tool result to the TUI so that file-changes and web
            # sources accumulate in the main chat panel even when the user is
            # running in Creator Mode (previously this only worked for Agent
            # / Normal modes because creator used its own graph).
            try:
                from Interface.tui_bridge import get_bridge as _get_bridge_ct
                _b = _get_bridge_ct()
                if _b is not None:
                    _b.on_tool_result(tool_name, result)
            except Exception:
                pass

            content_str = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, (dict, list)) else str(result)
            # Truncate for context saving
            if len(content_str) > 3000:
                content_str = content_str[:1500] + "\n…[truncated]…\n" + content_str[-1500:]
            results.append(ToolMessage(content=content_str, tool_call_id=tool_call_id, name=tool_name))
        return {"messages": results}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return END

    wf = StateGraph(state_schema=MessagesState)
    wf.add_node("agent", call_model)
    wf.add_node("tools", execute_tools)
    wf.set_entry_point("agent")
    wf.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    wf.add_edge("tools", "agent")
    return wf.compile()


def _is_auth_error(exc: Exception) -> bool:
    """Проверить, является ли ошибка проблемой аутентификации."""
    msg = str(exc).lower()
    return any(p in msg for p in ("401", "403", "unauthorized", "forbidden", "authentication"))


_MAX_DEPTH = 5


def _run_single_worker(
    worker_id: str,
    task: str,
    tools: List[BaseTool],
    model_type: str,
    llm: ChatOpenAI,
    model_name: str,
    display: Optional[Any] = None,
    project_context: str = "",
    depth: int = 0,
    role: str = "implementer",
    peer_memo: str = "",
    orchestration: str = "parallel",
) -> Dict[str, Any]:
    """Запустить одного воркера-агента.

    Если локальная модель возвращает 401 — автоматически переключается на heavy.
    Может рекурсивно порождать дочерних воркеров (depth контролирует глубину).

    Returns:
        {"worker_id", "task", "status", "result", "tool_calls", "rounds", "elapsed", "children"}
    """
    start_time = time.time()

    # Обновить граф
    if display:
        display.update_worker(
            worker_id,
            status="working",
            start_time=start_time,
            model_name=model_name,
            model_type=model_type,
        )

    orch = normalize_orchestration(orchestration)
    worker_system = (
        f"{SYSTEM_PROMPT}\n\n{project_context}\n\n"
        + format_worker_mode_section(worker_id, role, orch)
    )

    # Build spawn_sub_creator tool for recursive delegation
    sub_results: List[Dict[str, Any]] = []

    if depth < _MAX_DEPTH:
        from langchain_core.tools import tool as lc_tool

        @lc_tool
        def spawn_sub_creator(subtask: str) -> Dict[str, Any]:
            """Делегировать подзадачу дочернему агенту. Используй если задача слишком сложная и её можно разбить на подзадачи."""
            child_result = run_creator_mode(
                task=subtask,
                tools=tools,
                project_context=project_context,
                depth=depth + 1,
                parent_worker_id=worker_id,
            )
            sub_results.append(child_result)
            done = child_result.get("workers_done", 0)
            total = child_result.get("workers_total", 0)
            return {
                "status": child_result.get("status", "unknown"),
                "workers_done": done,
                "workers_total": total,
                "summary": f"Sub-creator: {done}/{total} tasks done",
            }

        worker_tools = list(tools) + [spawn_sub_creator]
    else:
        worker_tools = list(tools)

    messages = [
        SystemMessage(content=worker_system),
        HumanMessage(content=build_worker_user_content(task, peer_memo)),
    ]

    current_llm = llm
    current_model_name = model_name
    current_model_type = model_type

    try:
        from Interface.tui_bridge import get_bridge
        bridge = get_bridge()
        if bridge:
            bridge.on_creator_worker_update(worker_id, action=f"Старт: {task}")
    except Exception:
        bridge = None

    try:
        graph = _build_worker_graph(current_llm, worker_tools, current_model_name)
    except Exception as e:
        if _is_auth_error(e) and model_type == "local":
            try:
                heavy_llm, heavy_name = get_heavy_llm()
                current_llm = heavy_llm
                current_model_name = heavy_name
                current_model_type = "heavy"
                if display:
                    display.update_worker(
                        worker_id,
                        model_name=heavy_name,
                        model_type="heavy",
                    )
                graph = _build_worker_graph(current_llm, worker_tools, current_model_name)
            except Exception as e2:
                if display:
                    display.update_worker(worker_id, status="error", end_time=time.time())
                return {
                    "worker_id": worker_id, "task": task, "status": "error",
                    "result": f"Fallback failed: {e2}", "tool_calls": 0,
                    "rounds": 0, "elapsed": time.time() - start_time,
                }
        else:
            if display:
                display.update_worker(worker_id, status="error", end_time=time.time())
            return {
                "worker_id": worker_id, "task": task, "status": "error",
                "result": f"Failed to build graph: {e}", "tool_calls": 0,
                "rounds": 0, "elapsed": time.time() - start_time,
            }

    tool_count = 0
    round_num = 0
    final_content = ""

    try:
        for state in graph.stream({"messages": messages}, stream_mode="values"):
            messages = state["messages"]
            
            current_round_num = 0
            current_tool_count = 0
            
            for msg in messages:
                if isinstance(msg, AIMessage):
                    # Проверить на ошибку авторизации в контенте
                    msg_content = str(msg.content or "").strip()
                    if _is_auth_error(Exception(msg_content)) and current_model_type == "local" and current_round_num == 0:
                        # Первый раунд вернул ошибку авторизации — fallback
                        raise _AuthFallbackError(msg_content)

                    if msg.tool_calls:
                        current_round_num += 1
                        current_tool_count += len(msg.tool_calls)
                        if msg is messages[-1]:
                            t_names = ", ".join(tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "") for tc in msg.tool_calls)
                            action_text = msg_content if msg_content else f"Calling: {t_names}"
                            if display:
                                display.update_worker(
                                    worker_id,
                                    tool_calls=current_tool_count,
                                    rounds=current_round_num,
                                    current_action=action_text
                                )
                            if bridge:
                                bridge.on_creator_worker_update(
                                    worker_id,
                                    tool_name=t_names,
                                    action=action_text,
                                    thinking="",
                                )
                    elif msg_content and msg is messages[-1]:
                        final_content = msg_content
                        if display:
                            display.update_worker(worker_id, current_action="Finalizing")

            round_num = current_round_num
            tool_count = current_tool_count

            if round_num >= _MAX_WORKER_ROUNDS:
                break

    except _AuthFallbackError:
        # Fallback на heavy модель
        if current_model_type == "local":
            try:
                heavy_llm, heavy_name = get_heavy_llm()
                current_model_name = heavy_name
                current_model_type = "heavy"
                if display:
                    display.update_worker(
                        worker_id,
                        model_name=heavy_name,
                        model_type="heavy",
                        status="working",
                    )
                # Перезапустить с heavy
                messages_retry = [
                    SystemMessage(content=worker_system),
                    HumanMessage(content=build_worker_user_content(task, peer_memo)),
                ]
                graph_retry = _build_worker_graph(heavy_llm, worker_tools, heavy_name)
                for state in graph_retry.stream({"messages": messages_retry}, stream_mode="values"):
                    messages_retry = state["messages"]
                    
                    current_round_num = 0
                    current_tool_count = 0
                    
                    for msg in messages_retry:
                        if isinstance(msg, AIMessage):
                            msg_content = str(msg.content or "").strip()
                            if msg.tool_calls:
                                current_round_num += 1
                                current_tool_count += len(msg.tool_calls)
                                if msg is messages_retry[-1]:
                                    if display:
                                        t_names = ", ".join(tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "") for tc in msg.tool_calls)
                                        action_text = msg_content if msg_content else f"⚙️ Вызов: {t_names}"
                                        display.update_worker(
                                            worker_id, tool_calls=current_tool_count, rounds=current_round_num, current_action=action_text
                                        )
                            elif msg_content and msg is messages_retry[-1]:
                                final_content = msg_content
                                if display:
                                    display.update_worker(worker_id, current_action="💡 Финализация")
                                    
                    round_num = current_round_num
                    tool_count = current_tool_count

                    if round_num >= _MAX_WORKER_ROUNDS:
                        break
            except Exception as e:
                end_time = time.time()
                if display:
                    display.update_worker(worker_id, status="error", end_time=end_time, result_preview=str(e)[:80])
                return {
                    "worker_id": worker_id, "task": task, "status": "error",
                    "result": f"Heavy fallback error: {e}", "tool_calls": tool_count,
                    "rounds": round_num, "elapsed": end_time - start_time,
                }

    except Exception as e:
        end_time = time.time()
        if display:
            display.update_worker(
                worker_id, status="error", end_time=end_time,
                result_preview=str(e)[:80],
            )
        return {
            "worker_id": worker_id, "task": task, "status": "error",
            "result": str(e), "tool_calls": tool_count,
            "rounds": round_num, "elapsed": end_time - start_time,
        }

    end_time = time.time()
    
    final_status = "done"
    if round_num >= _MAX_WORKER_ROUNDS:
        final_status = "error"
        final_content = "Превышен лимит вызовов (MAX_WORKER_ROUNDS). Задача не была завершена."
        
    if display:
        display.update_worker(
            worker_id, status=final_status, end_time=end_time,
            result_preview=final_content[:80] if final_content else ("OK" if final_status == "done" else "LIMIT ERROR"),
            model_name=current_model_name,
            model_type=current_model_type,
        )

    result_data = {
        "worker_id": worker_id,
        "task": task,
        "status": final_status,
        "result": final_content,
        "tool_calls": tool_count,
        "rounds": round_num,
        "elapsed": end_time - start_time,
        "model_type": current_model_type,
        "model_name": current_model_name,
        "children": sub_results,
        "depth": depth,
    }

    # Push to TUI bridge if available
    try:
        from Interface.tui_bridge import get_bridge
        bridge = get_bridge()
        if bridge:
            tree_data = _build_tree_data(result_data)
            bridge.on_creator_tree(tree_data)
            fc = (final_content or "").strip()
            if fc:
                bridge.on_creator_worker_update(
                    worker_id,
                    tool_name="",
                    action="### Итог воркера" if final_status == "done" else "### Результат воркера",
                    thinking=fc,
                )
    except Exception:
        pass

    return result_data


def _build_tree_data(result: Dict[str, Any]) -> Dict[str, Any]:
    """Convert worker result to tree visualization data."""
    children = []
    for child in result.get("children", []):
        for cr in child.get("results", []):
            children.append(_build_tree_data(cr))
    return {
        "worker_id": result.get("worker_id", "?"),
        "task": result.get("task", ""),
        "status": result.get("status", "waiting"),
        "model_type": result.get("model_type", ""),
        "children": children,
    }


def _push_full_tree(bridge, task: str, worker_configs: list, results: list) -> None:
    """Push the full parallel worker tree to the TUI, showing all workers."""
    completed_ids = {r["worker_id"] for r in results}
    children = []
    for wc in worker_configs:
        wid = wc["worker_id"]
        matching = [r for r in results if r["worker_id"] == wid]
        if matching:
            children.append(_build_tree_data(matching[0]))
        else:
            children.append({
                "worker_id": wid,
                "task": wc.get("task", ""),
                "status": "working",
                "model_type": wc.get("model_type", ""),
                "children": [],
            })

    tree_data = {
        "worker_id": "orchestrator",
        "task": task[:60],
        "status": "working" if len(completed_ids) < len(worker_configs) else "done",
        "model_type": "creator",
        "children": children,
    }
    try:
        bridge.on_creator_tree(tree_data)
    except Exception:
        pass


# ─── Orchestrator ───────────────────────────────────────────────────

def run_creator_mode(
    task: str,
    tools: List[BaseTool],
    project_context: str = "",
    depth: int = 0,
    parent_worker_id: str = "",
) -> Dict[str, Any]:
    """Запустить Creator Mode для задачи.

    Args:
        task: Основная задача пользователя
        tools: Список инструментов доступных агентам
        project_context: Контекст проекта (структура, etc.)
        depth: Current recursion depth (0 = root)
        parent_worker_id: Parent worker ID for nested spawns

    Returns:
        {"status", "workers", "elapsed", "results"}
    """
    config = get_creator_config()
    max_workers = config["max_workers"]
    local_model = config["local_model"]
    local_base_url = config["local_base_url"]

    # Визуализация
    if GraphLiveDisplay is not None:
        display = GraphLiveDisplay(main_task=task)
    else:
        display = None

    try:
        # Импорт визуализации для логирования
        from Interface.visualization import (
            print_info, print_success, print_warning, print_error,
        )
    except ImportError:
        def print_info(m): print(f"  {m}")
        def print_success(m): print(f"  ✓ {m}")
        def print_warning(m): print(f"  ⚠ {m}")
        def print_error(m): print(f"  ✗ {m}")

    t_start = time.time()

    # Grab the UI bridge up-front so we can drive the in-chat progress block
    # from every phase (planning → routing → workers → supervisor → done).
    # Only the root Creator run owns the progress widget; nested
    # spawn_sub_creator calls re-use the parent's bridge for worker-level
    # updates but must not mount an extra block.
    try:
        from Interface.tui_bridge import get_bridge
        bridge = get_bridge()
    except Exception:
        bridge = None

    is_root_run = (int(depth or 0) == 0) and not (parent_worker_id or "").strip()

    def _emit_progress(
        phase: str = "",
        percent: float | None = None,
        completed: int | None = None,
        total: int | None = None,
    ) -> None:
        if bridge is None or not is_root_run:
            return
        try:
            bridge.on_creator_progress_update(
                phase=phase or "",
                percent=float(percent) if percent is not None else 0.0,
                completed=int(completed) if completed is not None else 0,
                total=int(total) if total is not None else 0,
            )
        except Exception:
            pass

    if is_root_run and bridge is not None:
        try:
            bridge.on_creator_progress_start(task=task, total_workers=0)
        except Exception:
            pass
        _emit_progress(phase="starting", percent=2.0)

    prev_auto_confirm = False
    try:
        import Agent.tools.terminal_tool as term_tool
        prev_auto_confirm = getattr(term_tool, "AUTO_CONFIRM", False)
        term_tool.AUTO_CONFIRM = True
    except ImportError:
        term_tool = None

    # === Фаза 1: Планирование ===
    print_info("Creator Mode: разбиваю задачу на подзадачи…")
    _emit_progress(phase="planning", percent=5.0)

    try:
        subtasks = build_plan(task)
    except Exception as e:
        print_error(f"Не удалось разбить задачу: {e}")
        if is_root_run and bridge is not None:
            try:
                bridge.on_creator_progress_finish(summary=f"Ошибка планирования: {e}")
            except Exception:
                pass
        return {"status": "error", "error": str(e)}

    if not subtasks:
        print_warning("Задача слишком простая для Creator Mode, выполняю как одну задачу")
        subtasks = [task]

    print_success(f"Подзадачи ({len(subtasks)}):")
    for i, st in enumerate(subtasks):
        print_info(f"  {i + 1}. {st}")

    _emit_progress(phase="planning", percent=10.0, completed=0, total=len(subtasks))

    # === Фаза 2: Проверка локального сервера ===
    local_available = check_local_server(local_base_url)
    if local_available:
        print_success(f"Локальный сервер доступен: {local_base_url}")
    else:
        print_warning(f"Локальный сервер недоступен ({local_base_url}), все задачи пойдут на heavy model")

    # === Фаза 3: Маршрутизация ===
    worker_configs: List[Dict[str, Any]] = []
    for i, subtask in enumerate(subtasks):
        if parent_worker_id:
            worker_id = f"{parent_worker_id}.{i + 1}"
        else:
            worker_id = f"W-{i + 1}"

        if local_available:
            complexity = classify_task_complexity(subtask, plan_steps=0)
            if complexity == "simple":
                try:
                    llm = get_local_llm(model_name=local_model, base_url=local_base_url)
                    worker_configs.append({
                        "worker_id": worker_id,
                        "task": subtask,
                        "llm": llm,
                        "model_name": local_model,
                        "model_type": "local",
                    })
                    continue
                except Exception:
                    pass  # Fallback to heavy

        # Heavy model
        llm, model_name = get_heavy_llm()
        worker_configs.append({
            "worker_id": worker_id,
            "task": subtask,
            "llm": llm,
            "model_name": model_name,
            "model_type": "heavy",
        })

    local_count = sum(1 for wc in worker_configs if wc["model_type"] == "local")
    heavy_count = sum(1 for wc in worker_configs if wc["model_type"] == "heavy")
    print_info(f"Маршрутизация: {local_count} local, {heavy_count} heavy")

    orchestration = normalize_orchestration(str(config.get("orchestration", "parallel")))
    roles = worker_roles_for_count(len(worker_configs), orchestration)
    for idx, wc in enumerate(worker_configs):
        wc["role"] = roles[idx] if idx < len(roles) else "implementer"
    print_info(f"Оркестрация Creator: {orchestration}")

    _emit_progress(
        phase="routing", percent=18.0,
        completed=0, total=len(worker_configs),
    )

    # === Фаза 4: Запуск агентов (параллель / конвейер) ===
    if display:
        for wc in worker_configs:
            w_info = WorkerInfo(
                worker_id=wc["worker_id"],
                task=wc["task"],
                model_type=wc["model_type"],
                model_name=wc["model_name"],
                status="waiting",
            )
            display.add_worker(w_info)
        display.set_phase("working")
        display.start()

    results: List[Dict[str, Any]] = []

    # Push initial full tree to TUI showing all workers as pending
    try:
        if bridge:
            _push_full_tree(bridge, task, worker_configs, results)
    except Exception:
        bridge = None

    _emit_progress(
        phase="working", percent=22.0,
        completed=0, total=len(worker_configs),
    )

    # 20 % reserved for planning/routing, 75 % for worker execution, 5 % for
    # supervisor synthesis (if any). Keep the curve monotonic so users never
    # see the bar drop.
    _work_start_pct = 22.0
    _work_end_pct = 92.0 if orchestration == "supervisor" else 97.0

    def _progress_for_completed(done_count: int) -> float:
        if not worker_configs:
            return _work_end_pct
        frac = max(0.0, min(1.0, done_count / float(len(worker_configs))))
        return _work_start_pct + frac * (_work_end_pct - _work_start_pct)

    try:
        if orchestration == "sequential":
            handoff = ""
            for wc in worker_configs:
                try:
                    r = _run_single_worker(
                        worker_id=wc["worker_id"],
                        task=wc["task"],
                        tools=tools,
                        model_type=wc["model_type"],
                        llm=wc["llm"],
                        model_name=wc["model_name"],
                        display=display,
                        project_context=project_context,
                        depth=depth,
                        role=wc.get("role", "implementer"),
                        peer_memo=handoff,
                        orchestration=orchestration,
                    )
                    results.append(r)
                except Exception as e:
                    results.append({
                        "worker_id": wc["worker_id"],
                        "task": wc.get("task", ""),
                        "status": "error",
                        "result": str(e),
                        "tool_calls": 0,
                        "rounds": 0,
                        "elapsed": 0,
                    })
                    if display:
                        display.update_worker(wc["worker_id"], status="error", result_preview=str(e)[:80])
                snippet = (results[-1].get("result") or "").strip()
                if len(snippet) > 8000:
                    snippet = snippet[:4000] + "\n…\n" + snippet[-3000:]
                handoff += (
                    f"\n### {results[-1].get('worker_id', '?')} "
                    f"({results[-1].get('status', '?')})\n{snippet}\n"
                )
                if bridge:
                    _push_full_tree(bridge, task, worker_configs, results)
                _emit_progress(
                    phase="working",
                    percent=_progress_for_completed(len(results)),
                    completed=len(results),
                    total=len(worker_configs),
                )
        else:
            effective_workers = min(max_workers, len(worker_configs))
            with ThreadPoolExecutor(max_workers=effective_workers) as executor:
                futures: Dict[Future, str] = {}
                for wc in worker_configs:
                    future = executor.submit(
                        _run_single_worker,
                        worker_id=wc["worker_id"],
                        task=wc["task"],
                        tools=tools,
                        model_type=wc["model_type"],
                        llm=wc["llm"],
                        model_name=wc["model_name"],
                        display=display,
                        project_context=project_context,
                        depth=depth,
                        role=wc.get("role", "implementer"),
                        peer_memo="",
                        orchestration=orchestration,
                    )
                    futures[future] = wc["worker_id"]

                for future in as_completed(futures):
                    worker_id = futures[future]
                    try:
                        result = future.result(timeout=300)
                        results.append(result)
                    except Exception as e:
                        results.append({
                            "worker_id": worker_id,
                            "task": "",
                            "status": "error",
                            "result": str(e),
                            "tool_calls": 0,
                            "rounds": 0,
                            "elapsed": 0,
                        })
                        if display:
                            display.update_worker(worker_id, status="error", result_preview=str(e)[:80])
                    if bridge:
                        _push_full_tree(bridge, task, worker_configs, results)
                    _emit_progress(
                        phase="working",
                        percent=_progress_for_completed(len(results)),
                        completed=len(results),
                        total=len(worker_configs),
                    )

    except KeyboardInterrupt:
        print_warning("Creator Mode прерван пользователем")
        if display:
            display.set_phase("error")
    finally:
        if term_tool is not None:
            term_tool.AUTO_CONFIRM = prev_auto_confirm
            
        if display:
            display.set_phase("done")
            display.stop()

    elapsed = time.time() - t_start

    # Сортировать результаты по worker_id
    results.sort(key=lambda r: r.get("worker_id", ""))

    supervisor_synthesis = ""
    if orchestration == "supervisor" and results:
        _emit_progress(
            phase="supervising", percent=95.0,
            completed=len(results), total=len(worker_configs),
        )
        try:
            sup_llm, _sup_name = get_heavy_llm()
            supervisor_synthesis = synthesize_supervisor_report(task, results, sup_llm)
            if supervisor_synthesis:
                preview = supervisor_synthesis[:2000] + ("…" if len(supervisor_synthesis) > 2000 else "")
                print_info(f"\n── Сводка супервайзера ──\n{preview}")
        except Exception as e:
            supervisor_synthesis = f"[supervisor error] {e}"
            print_warning(supervisor_synthesis)

    # === Фаза 5: Итоговый отчёт ===
    if display_creator_result and display:
        display_creator_result(display.workers, task, elapsed)
    else:
        # Fallback
        print_info(f"\nCreator Mode завершён за {elapsed:.1f}s")
        for r in results:
            icon = "✓" if r["status"] == "done" else "✗"
            print_info(f"  {icon} {r['worker_id']}: {r['task'][:50]}")

    done_count = sum(1 for r in results if r["status"] == "done")
    error_count = sum(1 for r in results if r["status"] == "error")

    if is_root_run and bridge is not None:
        try:
            final_phase = "error" if (error_count and not done_count) else "done"
            bridge.on_creator_progress_update(
                phase=final_phase, percent=100.0,
                completed=done_count, total=max(done_count, len(worker_configs)),
            )
            status_label = "завершено" if final_phase == "done" else (
                "частично" if done_count else "ошибка"
            )
            summary_line = (
                f"{status_label}: {done_count}/{len(results)} воркеров · {elapsed:.1f}s"
            )
            bridge.on_creator_progress_finish(summary=summary_line)
        except Exception:
            pass

    # Visualizing changed files
    modified_files = []
    try:
        from pathlib import Path
        t_start_run = t_start
        for p in Path.cwd().rglob("*"):
            if p.is_file() and not any(part.startswith('.') for part in p.parts):
                try:
                    if p.stat().st_mtime > t_start_run:
                        modified_files.append(str(p.relative_to(Path.cwd())))
                except (ValueError, FileNotFoundError):
                    pass
    except Exception:
        pass
        
    if modified_files:
        display_file_diffs(modified_files)

    return {
        "status": "done" if error_count == 0 else "partial",
        "workers_total": len(results),
        "workers_done": done_count,
        "workers_error": error_count,
        "elapsed": elapsed,
        "results": results,
        "orchestration": orchestration,
        "supervisor_synthesis": supervisor_synthesis or None,
    }
