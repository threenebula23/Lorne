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
    from .planner import build_plan
    from .system_promt import SYSTEM_PROMPT
except ImportError:
    from Agent.creator_provider import (
        get_local_llm, get_heavy_llm, classify_task_complexity,
        route_to_model, get_creator_config, check_local_server,
    )
    from Agent.planner import build_plan
    from Agent.system_promt import SYSTEM_PROMPT

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

_MAX_WORKER_ROUNDS = 15


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

    try:
        llm_with_tools = llm.bind_tools(tools)
    except Exception:
        llm_with_tools = llm.bind_tools(tools)

    def call_model(state: MessagesState) -> Dict[str, List[AIMessage]]:
        messages = state["messages"]
        try:
            response = llm_with_tools.invoke(messages)
        except Exception as e:
            return {"messages": [AIMessage(content=f"Ошибка: {e}")]}

        content = response.content or ""
        if isinstance(content, str):
            content = content.encode("utf-8", "ignore").decode("utf-8", "ignore")
        meta = getattr(response, "response_metadata", None) or {}

        if getattr(response, "tool_calls", None):
            return {"messages": [AIMessage(
                content=content, tool_calls=response.tool_calls, response_metadata=meta,
            )]}
        return {"messages": [AIMessage(content=content, response_metadata=meta)]}

    def execute_tools(state: MessagesState) -> Dict[str, List[Any]]:
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        results = []
        for tc in tool_calls:
            tc_dict = tc if isinstance(tc, dict) else {
                "name": getattr(tc, "name", ""),
                "args": getattr(tc, "args", {}),
                "id": getattr(tc, "id", ""),
            }
            tool_name = str(tc_dict.get("name", ""))
            tool_args = tc_dict.get("args", {}) or {}
            tool_call_id = str(tc_dict.get("id", f"call_{hash(tool_name)}"))

            tool_obj = tool_map.get(tool_name)
            if tool_obj is None:
                result = f"Unknown tool: {tool_name}"
            else:
                try:
                    result = tool_obj.invoke(tool_args)
                except Exception as e:
                    result = f"Error: {e}"

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


def _run_single_worker(
    worker_id: str,
    task: str,
    tools: List[BaseTool],
    model_type: str,
    llm: ChatOpenAI,
    model_name: str,
    display: Optional[Any] = None,
    project_context: str = "",
) -> Dict[str, Any]:
    """Запустить одного воркера-агента.

    Если локальная модель возвращает 401 — автоматически переключается на heavy.

    Returns:
        {"worker_id", "task", "status", "result", "tool_calls", "rounds", "elapsed"}
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

    # Системный промпт для воркера
    worker_system = f"""{SYSTEM_PROMPT}

{project_context}

=== РЕЖИМ ВОРКЕРА ===
Ты — воркер #{worker_id} в Creator Mode.
Выполни ОДНУ конкретную подзадачу. Работай эффективно и лаконично.
НЕ задавай вопросов — просто делай.
После завершения дай краткий отчёт что было сделано.
"""

    messages = [
        SystemMessage(content=worker_system),
        HumanMessage(content=f"Подзадача: {task}\n\nВыполни эту задачу."),
    ]

    # Попытка построить граф — с fallback на heavy при ошибке авторизации
    current_llm = llm
    current_model_name = model_name
    current_model_type = model_type

    try:
        graph = _build_worker_graph(current_llm, tools, current_model_name)
    except Exception as e:
        if _is_auth_error(e) and model_type == "local":
            # Fallback на heavy
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
                graph = _build_worker_graph(current_llm, tools, current_model_name)
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
                        if msg is messages[-1]:  # Update display only for the latest message
                            if display:
                                t_names = ", ".join(tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "") for tc in msg.tool_calls)
                                action_text = msg_content if msg_content else f"⚙️ Вызов: {t_names}"
                                display.update_worker(
                                    worker_id,
                                    tool_calls=current_tool_count,
                                    rounds=current_round_num,
                                    current_action=action_text
                                )
                    elif msg_content and msg is messages[-1]:
                        final_content = msg_content
                        if display:
                            display.update_worker(worker_id, current_action="💡 Финализация")

            round_num = current_round_num
            tool_count = current_tool_count

            if round_num >= _MAX_WORKER_ROUNDS:
                break

        # DEBUG: Dump the message history to figure out why workers get stuck
        with open(f".tca_creator_debug_{worker_id}.json", "w", encoding="utf-8") as f:
            debug_msgs = []
            for m in messages:
                if hasattr(m, "content"):
                    debug_msgs.append({"type": type(m).__name__, "content": str(m.content)[:500], "tool_calls": getattr(m, "tool_calls", None)})
            json.dump(debug_msgs, f, ensure_ascii=False, indent=2)

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
                    HumanMessage(content=f"Подзадача: {task}\n\nВыполни эту задачу."),
                ]
                graph_retry = _build_worker_graph(heavy_llm, tools, heavy_name)
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

    return {
        "worker_id": worker_id,
        "task": task,
        "status": final_status,
        "result": final_content,
        "tool_calls": tool_count,
        "rounds": round_num,
        "elapsed": end_time - start_time,
        "model_type": current_model_type,
        "model_name": current_model_name,
    }


# ─── Orchestrator ───────────────────────────────────────────────────

def run_creator_mode(
    task: str,
    tools: List[BaseTool],
    project_context: str = "",
) -> Dict[str, Any]:
    """Запустить Creator Mode для задачи.

    Args:
        task: Основная задача пользователя
        tools: Список инструментов доступных агентам
        project_context: Контекст проекта (структура, etc.)

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
    
    prev_auto_confirm = False
    try:
        import Agent.tools.terminal_tool as term_tool
        prev_auto_confirm = getattr(term_tool, "AUTO_CONFIRM", False)
        term_tool.AUTO_CONFIRM = True
    except ImportError:
        term_tool = None

    # === Фаза 1: Планирование ===
    print_info("Creator Mode: разбиваю задачу на подзадачи…")

    try:
        subtasks = build_plan(task)
    except Exception as e:
        print_error(f"Не удалось разбить задачу: {e}")
        return {"status": "error", "error": str(e)}

    if not subtasks:
        print_warning("Задача слишком простая для Creator Mode, выполняю как одну задачу")
        subtasks = [task]

    print_success(f"Подзадачи ({len(subtasks)}):")
    for i, st in enumerate(subtasks):
        print_info(f"  {i + 1}. {st}")

    # === Фаза 2: Проверка локального сервера ===
    local_available = check_local_server(local_base_url)
    if local_available:
        print_success(f"Локальный сервер доступен: {local_base_url}")
    else:
        print_warning(f"Локальный сервер недоступен ({local_base_url}), все задачи пойдут на heavy model")

    # === Фаза 3: Маршрутизация ===
    worker_configs: List[Dict[str, Any]] = []
    for i, subtask in enumerate(subtasks):
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

    # === Фаза 4: Запуск параллельных агентов ===
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

    try:
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
    }
