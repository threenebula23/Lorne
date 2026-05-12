"""Classic CLI agent loop."""
from __future__ import annotations

from ._impl_prepare import *  # noqa: F403
from ._impl_prepare import (
    _build_session_system_prompt,
    _init_llm,
    _print_creator_details,
    _refresh_runtime_tools,
    _should_autoplan,
)
def run_coding_agent_loop():
    global MODEL_NAME, MODEL_PROFILE, CONTEXT_LIMIT

    try:
        from Agent.path_utils import set_project_root

        set_project_root(Path.cwd())
    except Exception:
        pass

    print_info("Анализирую структуру проекта…")
    project_structure = analyze_project_structure()

    custom_tools_section = get_custom_tools_prompt()
    # Tool names are already in the JSON schemas bound to the LLM; duplicating
    # them here used to add ~200 tok/turn with no benefit. Keep the prompt lean.
    enhanced_system_prompt = _build_session_system_prompt(
        SYSTEM_PROMPT, custom_tools_section, project_structure
    )

    # Session selection
    sessions = list_sessions(limit=18)
    session_id = ""
    messages: List[Any] = []

    session_handled = False
    choice = ""
    if sessions:
        try:
            import questionary
            from questionary import Choice

            q_choices: List[Any] = [Choice("🆕 Новая сессия", "__new__")]
            for s in sessions:
                title = (s.get("title") or "без имени")[:46]
                mc = s.get("message_count", 0)
                upd = str(s.get("updated_at", ""))[:19]
                label = f"{title}  ({mc} msg)  {upd}"
                q_choices.append(Choice(label, s["session_id"]))
            q_choices.append(Choice("🗑 Удалить сессию…", "__delete__"))
            picked = questionary.select(
                "Выберите чат или действие",
                choices=q_choices,
            ).ask()
            if picked == "__delete__":
                del_opts = [
                    Choice(
                        f"{(s.get('title') or '?')[:40]}  ({s.get('message_count', 0)} msg)",
                        s["session_id"],
                    )
                    for s in sessions
                ]
                victim = questionary.select("Какую сессию удалить?", choices=del_opts).ask()
                if victim:
                    delete_session(victim)
                    print_success("Сессия удалена.")
                session_id = create_session("new-chat")
                messages = [SystemMessage(content=enhanced_system_prompt)]
                print_success(f"Новая сессия: {session_id}")
                session_handled = True
            elif picked and picked != "__new__":
                choice = str(picked)
            else:
                choice = ""
        except ImportError:
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
            except Exception:
                try:
                    choice = get_user_input().strip()
                except (EOFError, KeyboardInterrupt):
                    choice = ""
        except (EOFError, KeyboardInterrupt):
            choice = ""
        except Exception:
            try:
                choice = get_user_input().strip()
            except (EOFError, KeyboardInterrupt):
                choice = ""
    else:
        choice = ""

    if session_handled:
        pass
    elif not choice:
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

    # Welcome + balance (единый баннер — см. print_startup_banner)
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
    try:
        from Interface.visualization import refresh_cli_ui_from_prefs

        refresh_cli_ui_from_prefs(force=True)
    except Exception:
        pass
    print_startup_banner(
        MODEL_NAME,
        MODEL_PROFILE,
        Path.cwd().name,
        balance_str,
        mode_label="Classic CLI",
    )
    print_commands()

    # Unified classic mode state (normal|agent|deep|creator|research).
    creator_mode_active = [False]
    research_mode_active = [False]
    classic_mode_state = ["agent"]
    stop_requested = [False]

    def _sync_classic_tool_bundle(mode: str) -> None:
        """Align classic CLI toolset with the same mode rules as the TUI."""
        ml = (mode or "agent").lower()
        ask = ml == "ask"
        agent_extras = ml in ("creator", "deep", "research")
        pw = False
        bw = True
        ct = True
        try:
            from Interface.ui_prefs import load_prefs
            prefs = load_prefs()
            ct = bool(prefs.get("custom_tools_enabled", True))
            if agent_extras:
                pw = bool(prefs.get("playwright_python_enabled", False))
                bw = bool(prefs.get("browser_tools_enabled", True))
        except Exception:
            pass
        try:
            from Agent.tool_registry import set_tool_session_prefs, build_tools
            set_tool_session_prefs(
                agent_mode=agent_extras,
                ask_mode=ask,
                playwright_python=pw,
                browser_tools=bw,
                custom_tools=ct,
            )
            fresh, _ = build_tools(
                agent_mode=agent_extras,
                ask_mode=ask,
                playwright_python=pw,
                browser_tools=bw,
                custom_tools=ct,
            )
            tools.clear()
            tools.extend(fresh)
            _refresh_runtime_tools()
        except Exception:
            pass

    class _ClassicBridge:
        """Мост Rich-вывода для Deep Solver в classic CLI (раньше тулы/ответы глотались)."""

        def __init__(self) -> None:
            self._is_classic: bool = True
            self._status_last_ts: float = 0.0
            self._deep_banner_shown: bool = False
            self._tool_seq: int = 0

        def on_info(self, message: str) -> None:
            print_info(message)

        def on_warning(self, message: str) -> None:
            print_warning(message)

        def on_error(self, message: str) -> None:
            print_error(message)

        def on_thought(self, message: str) -> None:
            print_thinking(message)

        def on_model_reply(self, text: str, _usage: Any = None) -> None:
            t = (text or "").strip()
            if t:
                display_model_reply(0, t, None)

        def on_tool_start(
            self, step_round: int, name: str, args: Any,
        ) -> None:
            a = args if isinstance(args, dict) else {"args": args}
            try:
                display_agent_action(int(step_round), str(name), a)
            except Exception:
                pass

        def on_tool_result(self, name: str, result: Any) -> None:
            self._tool_seq += 1
            try:
                display_tool_result(self._tool_seq, str(name), result)
            except Exception:
                pass

        def on_deep_status(
            self, *, running: bool, elapsed: str = "",
            checkpoints: int = 0, model: str = "", current_step: int = 0,
        ) -> None:
            if not running:
                return
            if not self._deep_banner_shown:
                self._deep_banner_shown = True
                try:
                    ctxl = int(get_context_limit(f"ollama/{model}")) or 32_768
                except Exception:
                    ctxl = 32_768
                try:
                    print_deep_cli_session_banner(str(model or "—"), ctxl)
                except Exception:
                    pass
            if not self._is_classic:
                now = time.time()
                if self._status_last_ts and (now - self._status_last_ts) < 3.0:
                    return
                self._status_last_ts = now
            try:
                print_deep_cli_heartbeat(
                    elapsed=elapsed or "00:00",
                    checkpoints=int(checkpoints or 0),
                    model=str(model or ""),
                    step_round=int(current_step or 0),
                    to_stderr=True,
                )
            except Exception:
                pass

        def on_deep_checkpoint(
            self, cp_id: str, index: int, title: str,
            summary: str = "", turn_index: int = 0,
        ) -> None:
            try:
                print_deep_cli_checkpoint(
                    int(index),
                    str(title or ""),
                    str(summary or ""),
                    str(cp_id or ""),
                )
            except Exception:
                pass

        def on_context_update(self, _used: int, _total: int) -> None:
            return

        def is_stop_requested(self) -> bool:
            return bool(stop_requested[0])

    _sync_classic_tool_bundle(classic_mode_state[0])

    def _set_classic_mode(mode: str) -> None:
        m = (mode or "agent").strip().lower()
        if m not in ("agent", "ask", "deep", "creator", "research", "brainer"):
            m = "agent"
        classic_mode_state[0] = m
        creator_mode_active[0] = m == "creator"
        research_mode_active[0] = m == "research"
        _sync_classic_tool_bundle(m)

    # ─── Run & render ───────────────────────────────────────────
    def _run_and_render(old_len: int) -> None:
        nonlocal messages

        section("Агент работает", "═")
        stop_requested[0] = False
        round_num = 1
        file_changes: List[Dict[str, Any]] = []
        cumulative_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        t_start = time.time()
        tool_count = 0

        # old_len = index of first *new* message for this run (all prior turns are 0..old_len-1).
        printed_len = old_len
        from Agent.stream_chat_mode import set_stream_chat_mode

        set_stream_chat_mode(classic_mode_state[0] or "agent")
        try:
            for state in agent_graph.stream({"messages": messages}, stream_mode="values"):
                if stop_requested[0]:
                    print_warning("Остановка выполнения по запросу пользователя")
                    break
                messages = state["messages"]
                # Walk new tail strictly by index (do not re-print assistant content from
                # earlier turns if the list is ever re-materialized in a new stream value).
                while printed_len < len(messages):
                    msg = messages[printed_len]
                    printed_len += 1
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

        except KeyboardInterrupt:
            print_warning("Прервано пользователем")
        except Exception as e:
            print_error(f"Ошибка агента: {type(e).__name__}: {e}")
        finally:
            try:
                m = (classic_mode_state[0] or "").lower()
                if m == "brainer" and stop_requested[0]:
                    import os

                    if os.environ.get("LORNE_SKIP_BRAIN_SYNC", "").strip().lower() not in (
                        "1", "true", "yes", "on",
                    ):
                        from Agent.path_utils import get_project_root
                        from Agent.project_brain import refresh_project_brain
                        from Agent.project_brain.agent_architecture import reindex_brain_rag

                        r = get_project_root().resolve()
                        refresh_project_brain(r)
                        reindex_brain_rag(r)
            except Exception:
                pass
            try:
                from Agent.stream_chat_mode import set_stream_chat_mode

                set_stream_chat_mode(None)
            except Exception:
                pass

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
        "AVAILABLE_MODELS": get_available_models(),
        "set_model": set_model,
        "fetch_openrouter_credits": fetch_openrouter_credits,
        "format_credits_info": format_credits_info,
        "save_state": save_state,
        "creator_mode_active": creator_mode_active,
        "research_mode_active": research_mode_active,
        "mode_state": classic_mode_state,
        "stop_requested": stop_requested,
        "get_creator_config": get_creator_config,
        "save_creator_config": save_creator_config,
        "check_local_server": check_local_server,
        "run_creator_mode": run_creator_mode,
        "project_structure": project_structure,
        "print_creator_details": _print_creator_details,
        "run_and_render": _run_and_render,
        "agent_graph": agent_graph,
        "refresh_runtime_tools": _refresh_runtime_tools,
        "set_mode": _set_classic_mode,
        "get_deep_checkpoints": lambda: __import__(
            "Agent.deep_solver", fromlist=["list_checkpoints"]
        ).list_checkpoints(),
        "apply_deep_checkpoint": lambda cp_id, action: __import__(
            "Agent.deep_solver", fromlist=["apply_checkpoint_action"]
        ).apply_checkpoint_action(
            cp_id=cp_id,
            action=action,
            messages=messages,
            enhanced_system_prompt=enhanced_system_prompt,
            session_id=session_id,
            bridge=_ClassicBridge(),
        ),
    }
    router = CommandRouter(cmd_ctx)

    from Agent.command_router._main import _sync_router_model_ctx

    # ─── Main input loop ────────────────────────────────────────
    while True:
        try:
            from Interface.input_widget import get_user_input_advanced
            user_input = get_user_input_advanced(Path.cwd()).strip()
        except Exception:
            user_input = get_user_input().strip()

        # Keep cmd_ctx in sync with mutable globals
        cmd_ctx["model_name"] = MODEL_NAME
        cmd_ctx["model_profile"] = MODEL_PROFILE
        cmd_ctx["context_limit"] = CONTEXT_LIMIT

        result = router.handle(user_input)
        _sync_router_model_ctx(cmd_ctx)
        pending_cmd = cmd_ctx.pop("pending_user_input", None)
        if result == "exit":
            break
        if result is True and pending_cmd is None:
            continue
        if pending_cmd is not None:
            user_input = str(pending_cmd).strip()

        # Auto-compact if approaching context limit
        non_system_count = len([m for m in messages if not isinstance(m, SystemMessage)])
        # Trigger earlier + keep fewer recent turns — tool results
        # (file reads, web fetches) are the dominant cost for long sessions.
        if non_system_count > 20:
            messages = compact_conversation(messages, keep_last=8)
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
            summary_text = format_creator_summary_text(creator_result)
            try:
                display_model_reply(0, summary_text, None)
            except Exception:
                pass
            _print_creator_details(creator_result, worker_panels=False)
            messages.append(HumanMessage(content=f"[Creator Mode результат]\n{summary_text}"))
            messages.append(AIMessage(content=summary_text))
            try:
                save_state(messages, session_id=session_id)
            except Exception:
                pass
            continue
        else:
            mode_now = (classic_mode_state[0] or "agent").lower()
            if research_mode_active[0] and not user_input.startswith("/"):
                try:
                    from Interface.ui_prefs import load_prefs as _load_prefs
                    _rp = _load_prefs()
                    _src = int(_rp.get("research_max_sources", 6) or 6)
                    _rounds = int(_rp.get("research_max_rounds", 3) or 3)
                    _deep = bool(_rp.get("research_deep_fetch", True))
                except Exception:
                    _src, _rounds, _deep = 6, 3, True
                fetch_hint = (
                    "; при необходимости углубляйся в источники через web_fetch"
                    if _deep else "; без глубокого web_fetch, только web_search"
                )
                user_input = (
                    "[RESEARCH MODE ACTIVE]\n"
                    f"Используй web_search (до {_src} источников, {_rounds} раундов уточнения){fetch_hint}.\n"
                    "Ответь с источниками в формате [N] url.\n\n"
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
                            try:
                                from Agent.tool_registry import plan_tool
                            except ImportError:
                                from tool_registry import plan_tool
                            plan_tool.invoke({
                                "action": "save",
                                "title": user_input[:120],
                                "steps_json": json.dumps(steps, ensure_ascii=False),
                            })
                            plan_tool.invoke({
                                "action": "update",
                                "step_index": 0,
                                "status": "in_progress",
                                "note": "",
                            })
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
                            "ПЛАН УЖЕ СОХРАНЁН через plan_tool(action='save', …). НЕ вызывай save снова.\n"
                            "Выполняй шаги по порядку, начиная с шага 0:\n"
                            "1. plan_tool(action='update', step_index=N, status='in_progress') — перед началом шага\n"
                            "2. Выполни нужные действия (создай файл, запусти команду и т.д.)\n"
                            "3. ПРОВЕРЬ результат — если ошибка, исправь её, НЕ отмечай как completed\n"
                            "4. plan_tool(action='update', step_index=N, status='completed') — только если шаг успешен\n\n"
                            "ВАЖНО: Если нужно создать файл и запустить его — СНАЧАЛА создай файл, ПОТОМ запускай.\n"
                            "После выполнения дай чёткий ответ на РУССКОМ: что сделано, какие файлы, как запустить."
                        )
                    )
                )
            else:
                messages.append(HumanMessage(content=user_input))

        mode_now = (classic_mode_state[0] or "agent").lower()
        if mode_now == "deep":
            from Agent.deep_solver import run_deep_solver
            print_info("Deep mode: автономный запуск локального Deep Solver…")
            stop_requested[0] = False
            summary = run_deep_solver(
                task=user_input,
                tools=tools,
                bridge=_ClassicBridge(),
                project_context=project_structure,
                session_id=session_id,
                messages=messages,
            )
            if summary:
                display_model_reply(0, summary, None)
                messages.append(AIMessage(content=summary))
            try:
                save_state(messages, session_id=session_id)
            except Exception:
                pass
            continue

        old_len = len(messages)
        _run_and_render(old_len)


