"""
TCA Agent — Terminal Coding Assistant.
LangGraph-based agent loop with beautiful terminal output, conversation compaction,
error recovery, and Claude Code-inspired UX.
"""
import json
import os
import sys
import time
from dotenv import load_dotenv
from pathlib import Path
from typing import Any, Dict, List, Optional

_AGENT_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

try:
    from .system_promt import SYSTEM_PROMPT
except ImportError:
    from system_promt import SYSTEM_PROMPT

try:
    from .path_utils import resolve_abs_path, set_project_root
except ImportError:
    try:
        from Agent.path_utils import resolve_abs_path, set_project_root
    except ImportError:
        def resolve_abs_path(path_str: str) -> Path:
            p = Path(path_str).expanduser()
            return (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()
        def set_project_root(root: Path | str) -> None:
            pass

try:
    from .tool_registry import (
        build_tools, build_tool_map, bind_tools_safe,
        reload_tools, get_custom_tools_prompt,
    )
    from .rag import index_documents
    from .checkpoint import create_session, delete_session, list_sessions, load_state, save_state
    from .graph_runner import AgentGraph
    from .message_utils import sanitize_messages, compact_conversation
    from .spinner import LiveSpinner
    from .command_router import CommandRouter, _should_autoplan
except ImportError:
    from Agent.tool_registry import (
        build_tools, build_tool_map, bind_tools_safe,
        reload_tools, get_custom_tools_prompt,
    )
    from Agent.rag import index_documents
    from Agent.checkpoint import create_session, delete_session, list_sessions, load_state, save_state
    from Agent.graph_runner import AgentGraph
    from Agent.message_utils import sanitize_messages, compact_conversation
    from Agent.spinner import LiveSpinner
    from Agent.command_router import CommandRouter, _should_autoplan

try:
    from .creator_mode import run_creator_mode
except ImportError:
    from Agent.creator_mode import run_creator_mode

try:
    from .creator_provider import get_creator_config, save_creator_config, check_local_server
except ImportError:
    from Agent.creator_provider import get_creator_config, save_creator_config, check_local_server

try:
    from .llm_provider import (
        get_llm, get_available_profiles, normalize_profile,
        AVAILABLE_MODELS, set_model, get_saved_model,
        fetch_openrouter_credits, format_credits_info,
        is_reasoning_model,
    )
except ImportError:
    from Agent.llm_provider import (
        get_llm, get_available_profiles, normalize_profile,
        AVAILABLE_MODELS, set_model, get_saved_model,
        fetch_openrouter_credits, format_credits_info,
        is_reasoning_model,
    )

try:
    from .planner import build_plan
except ImportError:
    from Agent.planner import build_plan

try:
    from Interface.visualization import (
        section, round_header,
        display_agent_action, display_tool_result, display_model_reply,
        display_turn_summary, display_usage, display_cumulative_usage,
        get_context_limit,
        print_welcome, print_commands, print_session_list,
        print_thinking, print_planning, print_info, print_success,
        print_warning, print_error, get_user_input,
        console, HAS_RICH,
    )
except ImportError:
    def section(title, char="="): print(f"\n--- {title} ---")
    def round_header(n): print(f"\n--- Round {n} ---")
    def display_agent_action(sn, name, args): print(f"  Tool: {name}")
    def display_tool_result(sn, name, result): print(f"  Result: {name}")
    def display_model_reply(sn, content, meta=None): print(content[:500] if content else "")
    def display_turn_summary(files): pass
    def display_usage(meta, limit=None, prefix="   "): return {}
    def display_cumulative_usage(cum, limit, name=""): pass
    def get_context_limit(name): return 128_000
    def print_welcome(m, p, n, b=""): print(f"TCA — {m}" + (f" | {b}" if b else ""))
    def print_commands(): print("  /help, /exit")
    def print_session_list(s): pass
    def print_thinking(t=""): print(f"  Thinking: {t}")
    def print_planning(t): print(f"  Planning: {t}")
    def print_info(m): print(f"  {m}")
    def print_success(m): print(f"  ✓ {m}")
    def print_warning(m): print(f"  ⚠ {m}")
    def print_error(m): print(f"  ✗ {m}")
    def get_user_input():
        try: return input("> ")
        except (KeyboardInterrupt, EOFError): return "/exit"
    console = None
    HAS_RICH = False

load_dotenv()

# ─── Tools ──────────────────────────────────────────────────────────
tools, _custom = build_tools()
_tool_map = build_tool_map(tools)

if _custom:
    print_info(f"Custom tools: загружено {len(_custom)} тулов")


def _refresh_runtime_tools() -> None:
    """Rebuild tool map and rebind current LLM runtime."""
    global _tool_map, llm_with_tools, agent_graph
    _tool_map = build_tool_map(tools)
    if llm is not None:
        llm_with_tools = bind_tools_safe(llm, MODEL_NAME, tools)
    if agent_graph is not None and llm_with_tools is not None:
        agent_graph.rebuild(llm_with_tools, MODEL_NAME, is_reasoning_model(MODEL_NAME))
        agent_graph.llm_raw = llm
        agent_graph.tool_map = _tool_map

# ─── Project analysis ──────────────────────────────────────────────
_SKIP_DIRS = {
    ".git", ".idea", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt",
}


def analyze_project_structure(root_path: Optional[Path] = None) -> str:
    if root_path is None:
        root_path = Path.cwd()

    lines = [f"Project: {root_path.name}", f"Root: {root_path}", ""]
    file_types: Dict[str, int] = {}
    total_files = 0
    total_dirs = 0

    def _tree(directory: Path, prefix: str = "", depth: int = 0, max_depth: int = 3):
        nonlocal total_files, total_dirs
        if depth > max_depth:
            return
        try:
            items = sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return

        visible = [i for i in items if i.name not in _SKIP_DIRS and not i.name.startswith(".")]
        for idx, item in enumerate(visible):
            is_last = idx == len(visible) - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "
            try:
                if item.is_dir():
                    total_dirs += 1
                    lines.append(f"{prefix}{connector}{item.name}/")
                    try:
                        _tree(item, prefix + extension, depth + 1, max_depth)
                    except OSError:
                        lines.append(f"{prefix}{extension}    … (каталог недоступен)")
                else:
                    try:
                        st = item.stat()
                    except OSError:
                        lines.append(
                            f"{prefix}{connector}{item.name} (недоступно)",
                        )
                        continue
                    total_files += 1
                    suffix = item.suffix or "(no ext)"
                    file_types[suffix] = file_types.get(suffix, 0) + 1
                    size_kb = st.st_size / 1024
                    size_str = (
                        f"{size_kb:.1f}KB" if size_kb >= 1 else f"{st.st_size}B"
                    )
                    lines.append(f"{prefix}{connector}{item.name} ({size_str})")
            except OSError:
                lines.append(f"{prefix}{connector}{item.name} (недоступно)")

    _tree(root_path)

    lines.append(f"\nStats: {total_files} files, {total_dirs} directories")
    if file_types:
        top_types = sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:8]
        lines.append("Types: " + ", ".join(f"{ext}: {cnt}" for ext, cnt in top_types))

    return "\n".join(lines)


# ─── LLM init ──────────────────────────────────────────────────────
MODEL_PROFILE = normalize_profile(os.getenv("TCA_PROFILE", "balanced"))
MODEL_NAME = ""
CONTEXT_LIMIT = get_context_limit("arcee-ai/trinity-large-preview:free")
llm = None
llm_with_tools = None
agent_graph: Optional[AgentGraph] = None


def _init_llm(profile: Optional[str] = None) -> None:
    global llm, llm_with_tools, MODEL_NAME, MODEL_PROFILE, CONTEXT_LIMIT, agent_graph
    if profile is None:
        profile = MODEL_PROFILE
    llm_obj, profile_name, model_name = get_llm(profile)
    MODEL_PROFILE = profile_name
    MODEL_NAME = model_name
    CONTEXT_LIMIT = get_context_limit(MODEL_NAME)
    llm = llm_obj
    llm_with_tools = bind_tools_safe(llm_obj, model_name, tools)

    if agent_graph is None:
        agent_graph = AgentGraph(
            llm_with_tools=llm_with_tools,
            llm_raw=llm,
            tool_map=_tool_map,
            model_name=MODEL_NAME,
            is_reasoning=is_reasoning_model(MODEL_NAME),
            bind_tools_fn=bind_tools_safe,
            tools_list=tools,
        )
    else:
        agent_graph.rebuild(llm_with_tools, MODEL_NAME, is_reasoning_model(MODEL_NAME))
        agent_graph.llm_raw = llm
        agent_graph.tool_map = _tool_map


_init_llm(MODEL_PROFILE)


# ─── Creator Mode details printer ──────────────────────────────────

def _print_creator_details(creator_result: dict):
    if not creator_result or not creator_result.get("results"):
        return

    if HAS_RICH and console:
        from rich.panel import Panel as RPanel
        from rich import box as rbox

        console.print("\n[bold]Детальные отчеты агентов:[/bold]")
        for r in creator_result.get("results", []):
            color = "green" if r["status"] == "done" else "red"
            icon = "✓" if r["status"] == "done" else "✗"
            task_title = r.get("task", "")
            title = f"[{color}]{icon} {r.get('worker_id', 'Unknown')}[/{color}] - {task_title[:60]}"
            content = str(r.get("result", "Нет данных"))
            console.print(RPanel(
                content, title=title, border_style=color,
                box=rbox.ROUNDED, padding=(1, 2),
            ))

        t_start = time.time() - creator_result.get("elapsed", 0)
        modified_files = []
        try:
            for p in Path.cwd().rglob("*"):
                if p.is_file() and not any(part.startswith('.') for part in p.parts):
                    if p.stat().st_mtime > t_start:
                        try:
                            modified_files.append(str(p.relative_to(Path.cwd())))
                        except ValueError:
                            pass
        except Exception:
            pass

        if modified_files:
            console.print("\n[bold green]Измененные файлы:[/bold green]")
            for f in sorted(modified_files):
                console.print(f"  [dim]-[/dim] {f}")
    else:
        print("\nДетальные отчеты агентов:")
        for r in creator_result.get("results", []):
            icon = "✓" if r["status"] == "done" else "✗"
            print(f"\n{icon} {r.get('worker_id', 'Unknown')} - {r.get('task', '')[:60]}")
            print("-" * 40)
            print(r.get("result", "Нет данных"))
            print("-" * 40)


# ─── Main loop ──────────────────────────────────────────────────────
def run_coding_agent_loop():
    global MODEL_NAME, MODEL_PROFILE, CONTEXT_LIMIT

    print_info("Анализирую структуру проекта…")
    project_structure = analyze_project_structure()

    custom_tools_section = get_custom_tools_prompt()
    enhanced_system_prompt = f"""{SYSTEM_PROMPT}
{custom_tools_section}

=== КОНТЕКСТ ПРОЕКТА ===
{project_structure}

=== ИНСТРУКЦИИ СЕССИИ ===
Ты знаешь структуру проекта. Используй это для:
1. Понимания какие файлы упоминаются
2. Навигации по проекту
3. Работы с существующими паттернами кодовой базы

Состояние сессии сохраняется между запусками (SQLite checkpoint). Используй rag_search для поиска по документам.
"""

    # Session selection
    sessions = list_sessions(limit=18)
    session_id = ""
    messages: List[Any] = []

    if sessions:
        print_session_list(sessions)
        print_info("Выбери сессию: Enter=новая | номер/ID=продолжить | d номер/ID=удалить")

        try:
            from simple_term_menu import TerminalMenu
            session_options = [" [Новая сессия] "] + [
                f" {s.get('title', 'без имени')[:40]:<40}  (сообщ.: {s.get('message_count', 0):>2}, {s.get('updated_at', '')}) "
                for s in sessions
            ]
            terminal_menu = TerminalMenu(
                session_options,
                title="Выберите сессию (Esc/q для новой):",
                clear_screen=False,
            )
            menu_entry_index = terminal_menu.show()

            if menu_entry_index is None or menu_entry_index == 0:
                choice = ""
            else:
                choice = str(menu_entry_index)
        except (ImportError, Exception):
            try:
                choice = get_user_input().strip()
            except (EOFError, KeyboardInterrupt):
                choice = ""
    else:
        choice = ""

    if not choice:
        session_id = create_session("new-chat")
        messages = [SystemMessage(content=enhanced_system_prompt)]
        print_success(f"Новая сессия: {session_id}")
    elif choice.startswith("/exit"):
        return
    else:
        parts = choice.split()
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd == "d" and arg:
            target = arg
            if target.isdigit() and 1 <= int(target) <= len(sessions):
                target = sessions[int(target) - 1]["session_id"]
            delete_session(target)
            session_id = create_session("new-chat")
            messages = [SystemMessage(content=enhanced_system_prompt)]
            print_success(f"Сессия удалена. Новая сессия: {session_id}")
        else:
            target = choice
            if target.isdigit() and 1 <= int(target) <= len(sessions):
                target = sessions[int(target) - 1]["session_id"]
            loaded = load_state(target)
            if loaded:
                restored = []
                for d in loaded:
                    t = d.get("type", "")
                    if t == "SystemMessage":
                        continue
                    if t == "HumanMessage":
                        restored.append(HumanMessage(content=d.get("content", "") or ""))
                    elif t == "AIMessage":
                        restored.append(AIMessage(content=d.get("content", "") or "", tool_calls=d.get("tool_calls", [])))
                    elif t == "ToolMessage":
                        restored.append(ToolMessage(content=str(d.get("content", "")), tool_call_id=d.get("tool_call_id", "")))
                messages = sanitize_messages(
                    [SystemMessage(content=enhanced_system_prompt)] + restored
                )
                session_id = target
                print_success(f"Сессия восстановлена: {session_id} ({len(restored)} сообщений)")
                tail = [m for m in restored if isinstance(m, (HumanMessage, AIMessage))][-4:]
                if tail:
                    print_info("Последние сообщения:")
                    for m in tail:
                        role = "You" if isinstance(m, HumanMessage) else "Assistant"
                        txt = (m.content or "").strip().replace("\n", " ")
                        print_info(f"  {role}: {txt[:120]}{'…' if len(txt) > 120 else ''}")
            else:
                session_id = create_session("new-chat")
                messages = [SystemMessage(content=enhanced_system_prompt)]
                print_warning(f"Сессия не найдена. Новая сессия: {session_id}")

    # RAG indexing with progress
    try:
        set_project_root(Path.cwd())
        try:
            from Interface.visualization import display_rag_progress
            n_rag = index_documents(str(Path.cwd()), pattern="*.py",
                                    progress_callback=display_rag_progress)
        except ImportError:
            n_rag = index_documents(str(Path.cwd()), pattern="*.py")
        from Agent.rag import get_index_stats
        stats = get_index_stats()
        print_info(f"RAG: {stats['chunks']} чанков из {stats['files']} файлов")
    except Exception:
        pass

    # Splash screen
    try:
        from Interface.splash import show_splash
        show_splash(MODEL_NAME)
    except Exception:
        pass

    # Welcome + balance
    balance_str = ""
    try:
        creds = fetch_openrouter_credits()
        if creds:
            usage = creds.get("usage", 0)
            limit = creds.get("limit")
            if limit is not None and limit > 0:
                remaining = max(0, limit - usage)
                balance_str = f"${remaining:.4f}"
            else:
                balance_str = f"исп. ${usage:.4f}"
    except Exception:
        pass
    print_welcome(MODEL_NAME, MODEL_PROFILE, Path.cwd().name, balance_str)
    print_commands()

    # Creator mode flag (mutable list so command_router can toggle it)
    creator_mode_active = [False]
    research_mode_active = [False]

    # ─── Run & render ───────────────────────────────────────────
    def _run_and_render(old_len: int) -> None:
        nonlocal messages

        section("Агент работает", "═")
        round_num = 1
        file_changes: List[Dict[str, Any]] = []
        cumulative_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        t_start = time.time()
        tool_count = 0

        printed_len = old_len
        try:
            for state in agent_graph.stream({"messages": messages}, stream_mode="values"):
                messages = state["messages"]
                chunk = messages[printed_len:]
                if not chunk:
                    continue
                for msg in chunk:
                    if isinstance(msg, AIMessage):
                        if msg.tool_calls:
                            round_header(round_num)
                            round_num += 1
                            tool_count += len(msg.tool_calls)
                            meta = getattr(msg, "response_metadata", None) or {}
                            u = display_usage(meta, CONTEXT_LIMIT)
                            for k in cumulative_usage:
                                cumulative_usage[k] = cumulative_usage.get(k, 0) + u.get(k, 0)

                        if (not msg.tool_calls) and msg.content and str(msg.content).strip():
                            meta = getattr(msg, "response_metadata", None) or {}
                            u = display_usage(meta, CONTEXT_LIMIT)
                            for k in cumulative_usage:
                                cumulative_usage[k] = cumulative_usage.get(k, 0) + u.get(k, 0)
                            display_model_reply(0, msg.content, None)

                    elif isinstance(msg, ToolMessage):
                        content = msg.content
                        if isinstance(content, str):
                            try:
                                content = json.loads(content)
                            except (TypeError, json.JSONDecodeError):
                                pass
                        tool_name = getattr(msg, "name", "tool") or "tool"
                        if isinstance(content, dict):
                            action = content.get("action")
                            if tool_name in ("edit_file", "write_file", "create_code_file", "append_code_snippet") and action:
                                file_changes.append(content)

                    printed_len = len(messages)

        except KeyboardInterrupt:
            print_warning("Прервано пользователем")
        except Exception as e:
            print_error(f"Ошибка агента: {type(e).__name__}: {e}")

        elapsed = time.time() - t_start

        if file_changes:
            display_turn_summary(file_changes)
        display_cumulative_usage(cumulative_usage, CONTEXT_LIMIT, MODEL_NAME)
        print_info(f"Завершено за {elapsed:.1f}с ({tool_count} инструментов, {round_num - 1} раундов)")

        try:
            save_state(messages, session_id=session_id)
        except Exception:
            pass

    # ─── Command router context ─────────────────────────────────
    cmd_ctx = {
        "messages": messages,
        "session_id": session_id,
        "tools": tools,
        "model_name": MODEL_NAME,
        "model_profile": MODEL_PROFILE,
        "context_limit": CONTEXT_LIMIT,
        "resolve_abs_path": resolve_abs_path,
        "analyze_project_structure": analyze_project_structure,
        "init_llm": _init_llm,
        "get_available_profiles": get_available_profiles,
        "AVAILABLE_MODELS": AVAILABLE_MODELS,
        "set_model": set_model,
        "fetch_openrouter_credits": fetch_openrouter_credits,
        "format_credits_info": format_credits_info,
        "save_state": save_state,
        "creator_mode_active": creator_mode_active,
        "research_mode_active": research_mode_active,
        "get_creator_config": get_creator_config,
        "save_creator_config": save_creator_config,
        "check_local_server": check_local_server,
        "run_creator_mode": run_creator_mode,
        "project_structure": project_structure,
        "print_creator_details": _print_creator_details,
        "run_and_render": _run_and_render,
        "agent_graph": agent_graph,
        "refresh_runtime_tools": _refresh_runtime_tools,
    }
    router = CommandRouter(cmd_ctx)

    # ─── Main input loop ────────────────────────────────────────
    while True:
        user_input = get_user_input().strip()

        # Keep cmd_ctx in sync with mutable globals
        cmd_ctx["model_name"] = MODEL_NAME
        cmd_ctx["model_profile"] = MODEL_PROFILE
        cmd_ctx["context_limit"] = CONTEXT_LIMIT

        result = router.handle(user_input)
        if result == "exit":
            break
        if result is True:
            continue

        # Auto-compact if approaching context limit
        non_system_count = len([m for m in messages if not isinstance(m, SystemMessage)])
        if non_system_count > 30:
            messages = compact_conversation(messages, keep_last=10)
            cmd_ctx["messages"] = messages
            print_info("Авто-сжатие разговора для освобождения контекста")

        if not user_input:
            messages.append(HumanMessage(content="Продолжи, сделай следующий шаг если нужно."))
        elif creator_mode_active[0] and _should_autoplan(user_input):
            print_info("Creator Mode: запуск для задачи…")
            creator_result = run_creator_mode(
                task=user_input,
                tools=tools,
                project_context=project_structure,
            )
            _print_creator_details(creator_result)

            summary_parts = [f"Creator Mode выполнил задачу: {user_input}"]
            for r in creator_result.get("results", []):
                status_icon = "✓" if r["status"] == "done" else "✗"
                summary_parts.append(f"  {status_icon} {r['worker_id']}: {r['task'][:60]}")
                if r.get("result"):
                    summary_parts.append(f"    Результат: {r['result']}")
            summary_text = "\n".join(summary_parts)
            messages.append(HumanMessage(content=f"[Creator Mode результат]\n{summary_text}"))
            messages.append(AIMessage(content=summary_text))
            try:
                save_state(messages, session_id=session_id)
            except Exception:
                pass
            continue
        else:
            if research_mode_active[0] and not user_input.startswith("/"):
                user_input = (
                    "[RESEARCH MODE ACTIVE]\n"
                    "Используй web_search/web_fetch и ответь с источниками.\n\n"
                    + user_input
                )
            if _should_autoplan(user_input):
                print_planning(user_input)
                plan_spinner = LiveSpinner("Составляю план")
                plan_spinner.start()
                try:
                    steps = build_plan(user_input)
                    plan_spinner.stop()
                    if steps:
                        try:
                            from .tool_registry import save_plan, update_plan
                            save_plan.invoke({"title": user_input[:120], "steps": steps})
                            update_plan.invoke({"step_index": 0, "status": "in_progress", "note": ""})
                            print_success(f"План создан: {len(steps)} шагов")
                        except Exception as e:
                            print_warning(f"Не удалось сохранить план: {e}")
                except Exception as e:
                    plan_spinner.stop()
                    print_warning(f"Планирование не удалось: {e}")

                messages.append(
                    HumanMessage(
                        content=(
                            f"Задача: {user_input}\n\n"
                            "ПЛАН УЖЕ СОХРАНЁН через save_plan(). НЕ вызывай save_plan() снова.\n"
                            "Выполняй шаги по порядку, начиная с шага 0:\n"
                            "1. update_plan(step_index=N, status='in_progress') — перед началом шага\n"
                            "2. Выполни нужные действия (создай файл, запусти команду и т.д.)\n"
                            "3. ПРОВЕРЬ результат — если ошибка, исправь её, НЕ отмечай как completed\n"
                            "4. update_plan(step_index=N, status='completed') — только если шаг успешен\n\n"
                            "ВАЖНО: Если нужно создать файл и запустить его — СНАЧАЛА создай файл, ПОТОМ запускай.\n"
                            "После выполнения дай чёткий ответ на РУССКОМ: что сделано, какие файлы, как запустить."
                        )
                    )
                )
            else:
                messages.append(HumanMessage(content=user_input))

        old_len = len(messages)
        _run_and_render(old_len)


def run_tui_mode():
    """Launch TCA in full-screen Textual TUI mode."""
    try:
        from Interface.start_screen import select_project_path
    except Exception:
        select_project_path = None

    if select_project_path is not None:
        try:
            chosen_path = select_project_path(Path.cwd())
        except Exception:
            chosen_path = Path.cwd()
        if not chosen_path:
            return
        try:
            os.chdir(Path(chosen_path).resolve())
        except Exception:
            pass

    try:
        from Interface.tui_app import TCAApp
        from Interface.tui_bridge import TUIBridge, set_bridge
    except ImportError as e:
        print(f"Textual не доступен: {e}")
        print("Запуск в обычном режиме…")
        run_coding_agent_loop()
        return

    import sys
    import threading
    import traceback

    load_dotenv()
    _init_llm(MODEL_PROFILE)

    print_info("Анализирую структуру проекта…")
    project_structure = analyze_project_structure()

    custom_tools_section = get_custom_tools_prompt()
    enhanced_system_prompt = f"""{SYSTEM_PROMPT}
{custom_tools_section}

=== КОНТЕКСТ ПРОЕКТА ===
{project_structure}

=== ИНСТРУКЦИИ СЕССИИ ===
Ты знаешь структуру проекта. Используй это для навигации и работы с кодовой базой.
Используй rag_search для поиска по документам. Используй think() чтобы записывать свои рассуждения.
"""

    session_id = create_session("tui-session")
    messages: List[Any] = [SystemMessage(content=enhanced_system_prompt)]

    try:
        set_project_root(Path.cwd())
        index_documents(str(Path.cwd()), pattern="*.py")
    except Exception:
        pass

    try:
        from Agent.git_integration import get_git_manager
        gm = get_git_manager()
        git_branch = gm.current_branch() if gm.available else ""
    except Exception:
        git_branch = ""

    creator_mode_active = [False]
    research_mode_active = [False]
    tui_agent_mode = ["normal"]

    def _format_creator_summary(cr: Dict[str, Any]) -> str:
        if not cr:
            return "Creator mode finished."
        lines = [
            f"**Creator mode** — {cr.get('status', '?')} | "
            f"workers OK: {cr.get('workers_done', 0)}/{cr.get('workers_total', 0)} | "
            f"{cr.get('elapsed', 0):.1f}s",
        ]
        for r in cr.get("results", [])[:24]:
            wid = r.get("worker_id", "?")
            st = r.get("status", "?")
            res = str(r.get("result", ""))[:800]
            lines.append(f"\n### {wid} ({st})\n{res}")
        return "\n".join(lines)

    def handle_chat_submit(text: str):
        """Called from TUI when user sends a chat message (already in bg thread via Textual)."""
        nonlocal messages

        if not text.strip():
            text = "Продолжи, сделай следующий шаг если нужно."

        def _do_work():
            nonlocal messages
            try:
                cmd_ctx = {
                    "messages": messages,
                    "session_id": session_id,
                    "tools": tools,
                    "model_name": MODEL_NAME,
                    "model_profile": MODEL_PROFILE,
                    "context_limit": CONTEXT_LIMIT,
                    "resolve_abs_path": resolve_abs_path,
                    "analyze_project_structure": analyze_project_structure,
                    "init_llm": _init_llm,
                    "get_available_profiles": get_available_profiles,
                    "AVAILABLE_MODELS": AVAILABLE_MODELS,
                    "set_model": set_model,
                    "fetch_openrouter_credits": fetch_openrouter_credits,
                    "format_credits_info": format_credits_info,
                    "save_state": save_state,
                    "creator_mode_active": creator_mode_active,
                    "research_mode_active": research_mode_active,
                    "get_creator_config": get_creator_config,
                    "save_creator_config": save_creator_config,
                    "check_local_server": check_local_server,
                    "run_creator_mode": run_creator_mode,
                    "project_structure": project_structure,
                    "print_creator_details": _print_creator_details,
                    "run_and_render": lambda old_len: _tui_run(old_len, messages, bridge),
                    "agent_graph": agent_graph,
                    "refresh_runtime_tools": _refresh_runtime_tools,
                }

                from Agent.command_router import CommandRouter
                router = CommandRouter(cmd_ctx)
                result = router.handle(text)

                if result == "exit":
                    app.call_from_thread(app.exit)
                    return
                if result is True:
                    return

                mode = (tui_agent_mode[0] or "normal").lower()
                human_content = text
                if mode == "research" and not text.strip().lower().startswith("/"):
                    bridge.on_info("🔬 Research mode active")
                    human_content = (
                        "[Research mode — use web_search, web_fetch, multiple sources]\n\n"
                        + text
                    )

                messages.append(HumanMessage(content=human_content))
                bridge.on_separator("Round")

                if mode == "creator":
                    bridge.on_agent_start()
                    try:
                        creator_result = run_creator_mode(
                            task=text,
                            tools=tools,
                            project_context=project_structure,
                        )
                        summary = _format_creator_summary(creator_result)
                        bridge.on_model_reply(summary)
                        messages.append(AIMessage(content=summary))
                    except Exception as ce:
                        bridge.on_error(f"Creator error: {ce}")
                    finally:
                        bridge.on_agent_done()
                else:
                    _tui_run(len(messages), messages, bridge)

            except Exception as e:
                tb = traceback.format_exc()
                print(f"[TCA Worker Error] {tb}", file=sys.stderr)
                try:
                    bridge.on_error(f"{type(e).__name__}: {e}")
                except Exception:
                    try:
                        app.call_from_thread(
                            app.notify, f"Error: {e}", severity="error"
                        )
                    except Exception:
                        pass

        threading.Thread(target=_do_work, daemon=True).start()

    def _tui_run(old_len, msgs, bridge_ref):
        bridge_ref.clear_stop()
        bridge_ref.on_agent_start()
        try:
            cumulative = {"input_tokens": 0, "output_tokens": 0}
            for state in agent_graph.stream({"messages": msgs}, stream_mode="values"):
                if bridge_ref.is_stop_requested():
                    bridge_ref.on_warning("Agent stopped by user")
                    break
                msgs.clear()
                msgs.extend(state["messages"])
                new_msgs = msgs[old_len:]
                for msg in new_msgs:
                    if isinstance(msg, AIMessage):
                        meta = getattr(msg, "response_metadata", {}) or {}
                        usage = meta.get("usage", meta.get("token_usage", {}))
                        if isinstance(usage, dict):
                            inp = usage.get("prompt_tokens", usage.get("input_tokens", 0))
                            out = usage.get("completion_tokens", usage.get("output_tokens", 0))
                            cumulative["input_tokens"] += inp
                            cumulative["output_tokens"] += out
                            total_used = cumulative["input_tokens"] + cumulative["output_tokens"]
                            bridge_ref.on_context_update(total_used, CONTEXT_LIMIT)

                        content = str(msg.content or "").strip()
                        if content and not getattr(msg, "tool_calls", None):
                            bridge_ref.on_model_reply(content)
                old_len = len(msgs)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[TCA Agent Error] {tb}", file=sys.stderr)
            bridge_ref.on_error(f"Agent error: {type(e).__name__}: {e}")
        finally:
            bridge_ref.on_agent_done()

        try:
            save_state(msgs, session_id=session_id)
        except Exception:
            pass

        bridge_ref.on_status_update(
            model=MODEL_NAME,
            branch=git_branch,
            tokens=f"{len(msgs)} msgs",
        )

    def handle_model_change(model_id: str):
        """Called when user changes model in the TUI."""
        def _work():
            try:
                set_model(model_id)
                _init_llm()
            except Exception as e:
                bridge.on_error(f"Model error: {e}")
        threading.Thread(target=_work, daemon=True).start()

    def handle_mode_toggle(mode: str):
        """Called when user changes the agent mode."""
        mode_lower = (mode or "normal").lower() if isinstance(mode, str) else "normal"
        if mode_lower not in ("normal", "creator", "research", "agent"):
            mode_lower = "normal"
        tui_agent_mode[0] = mode_lower
        creator_mode_active[0] = mode_lower == "creator"
        research_mode_active[0] = mode_lower == "research"
        try:
            if mode_lower == "creator":
                app.call_from_thread(
                    app.chat.update_creator_tree,
                    {"worker_id": "creator", "status": "working", "task": "Creator mode", "children": []},
                )
            elif mode_lower == "research":
                app.call_from_thread(
                    app.chat.update_creator_tree,
                    {
                        "worker_id": "research",
                        "status": "working",
                        "task": "Research mode",
                        "model_type": "research",
                        "children": [{"worker_id": "web-search", "status": "working", "task": "Web + docs"}],
                    },
                )
            elif mode_lower == "agent":
                app.call_from_thread(
                    app.chat.update_creator_tree,
                    {"worker_id": "agent", "status": "working", "task": "Agent mode", "children": []},
                )
            else:
                app.call_from_thread(
                    app.chat.update_creator_tree,
                    {"worker_id": "idle", "status": "pending", "task": "No active mode", "children": []},
                )
        except Exception:
            pass

    app = TCAApp(
        model_name=MODEL_NAME,
        branch=git_branch,
        models=AVAILABLE_MODELS,
        on_chat_submit=handle_chat_submit,
        on_model_change=handle_model_change,
        on_mode_toggle=handle_mode_toggle,
    )
    bridge = TUIBridge(app)
    app.set_bridge(bridge)
    set_bridge(bridge)

    app.run()
    set_bridge(None)


if __name__ == "__main__":
    mode = os.getenv("TCA_MODE", "tui").lower()
    if mode == "classic":
        run_coding_agent_loop()
    else:
        run_tui_mode()
