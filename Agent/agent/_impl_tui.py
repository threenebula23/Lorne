"""Точка входа TUI для агента Lorne."""
from __future__ import annotations

from Agent.runtime_paths import env_pref

from ._impl_prepare import *  # noqa: F403
from ._impl_prepare import (
    _build_session_system_prompt,
    _init_llm,
    _print_creator_details,
    _refresh_runtime_tools,
    _sync_tui_tool_bundle,
)
from ._impl_classic import *  # noqa: F403
def _tui_generate_session_title(first_user_text: str) -> str:
    """Короткое название чата по первому запросу (один вызов LLM)."""
    global llm
    if not llm or not (first_user_text or "").strip():
        return ""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        out = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "Ответь одной строкой: краткое название чата на русском, до 60 символов, "
                        "без кавычек. Только заголовок."
                    )
                ),
                HumanMessage(content=first_user_text.strip()[:4000]),
            ]
        )
        t = str(getattr(out, "content", "") or "").strip().split("\n")[0][:80]
        return t
    except Exception:
        return ""


def run_tui_mode():
    """Запуск полноэкранного TUI (Textual)."""
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
            np = Path(chosen_path).resolve()
            os.chdir(np)
            try:
                from Agent.path_utils import set_project_root

                set_project_root(np)
            except Exception:
                pass
        except Exception:
            pass

    try:
        from Interface.tui_app import LorneApp
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
    enhanced_system_prompt = _build_session_system_prompt(
        SYSTEM_PROMPT, custom_tools_section, project_structure
    )

    session_id = ""
    messages: List[Any] = []
    title_flag = [False]

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
    tui_agent_mode = ["agent"]
    bridge_ref: List[Any] = [None]

    def apply_session_pick(result: dict) -> None:
        nonlocal session_id, messages, title_flag
        if result.get("action") == "new":
            session_id = create_session("")
            messages.clear()
            messages.append(SystemMessage(content=enhanced_system_prompt))
            title_flag[0] = False
        elif result.get("action") == "open":
            session_id = str(result.get("session_id", ""))
            messages.clear()
            raw = load_state(session_id) if session_id else None
            if raw:
                try:
                    messages.extend(messages_from_stored_dicts(raw, enhanced_system_prompt))
                except Exception:
                    messages.append(SystemMessage(content=enhanced_system_prompt))
            else:
                messages.append(SystemMessage(content=enhanced_system_prompt))
            title_flag[0] = True
        br = bridge_ref[0]
        if br:
            br.on_chat_reload_messages(list(messages))

    def handle_rollback(turn_index: int) -> None:
        def _work() -> None:
            nonlocal messages
            try:
                if not session_id:
                    return
                raw = load_pre_turn_snapshot(session_id, turn_index)
                if not raw:
                    br = bridge_ref[0]
                    if br:
                        br.on_error("Снимок для отката не найден")
                    return
                ws = restore_turn_workspace(session_id, turn_index)
                messages.clear()
                messages.extend(messages_from_stored_dicts(raw, enhanced_system_prompt))
                delete_turn_snapshots_from(session_id, turn_index)
                delete_turn_workspace_snapshots_from(session_id, turn_index)
                save_state(messages, session_id=session_id)
                br = bridge_ref[0]
                if br:
                    br.on_chat_reload_messages(list(messages))
                    if isinstance(ws, dict) and ws.get("ok"):
                        rf = int(ws.get("restored_files") or 0)
                        dn = int(ws.get("deleted_new_files") or 0)
                        br.on_info(f"Файлы: восстановлено версий {rf}, удалено новых файлов {dn}")
                    try:
                        br.on_file_changed("")
                    except Exception:
                        pass
            except Exception as e:
                br = bridge_ref[0]
                if br:
                    br.on_error(f"Откат: {e}")

        threading.Thread(target=_work, daemon=True).start()

    def handle_chat_submit(text: str, bubble_text: Optional[str] = None):
        """Called from TUI when user sends a chat message (bubble_text — текст в пузыре без префиксов)."""
        nonlocal messages

        if not text.strip():
            text = "Продолжи, сделай следующий шаг если нужно."

        try:
            from Agent.deep_solver import is_running as _deep_is_running, submit_user_message as _deep_push
        except Exception:  # pragma: no cover
            _deep_is_running = lambda: False  # type: ignore
            _deep_push = lambda _t: False  # type: ignore

        if _deep_is_running():
            display_plain = ((bubble_text or "").strip() or text)
            user_turn_idx = sum(1 for m in messages if isinstance(m, HumanMessage))
            messages.append(HumanMessage(content=text))
            try:
                bridge.on_chat_user_message(display_plain, user_turn_idx)
            except Exception:
                pass
            delivered = _deep_push(text)
            try:
                if delivered:
                    bridge.on_info(
                        "📨 Сообщение добавлено в очередь Deep Solver — "
                        "агент учтёт его на следующем шаге без перезапуска."
                    )
                else:
                    bridge.on_warning(
                        "Не удалось передать сообщение в Deep Solver, сессия "
                        "уже завершается."
                    )
            except Exception:
                pass
            try:
                save_state(messages, session_id=session_id)
            except Exception:
                pass
            return

        def _do_work():
            nonlocal messages
            # Copy outer ``text`` — assigning to ``text`` later in this function would
            # make ``text`` local for the whole body and break ``router.handle(text)``
            # with UnboundLocalError before that assignment runs.
            user_text = text
            try:
                _mode_now = (tui_agent_mode[0] or "agent").lower()
                _sync_tui_tool_bundle(_mode_now)
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
                    "get_creator_config": get_creator_config,
                    "save_creator_config": save_creator_config,
                    "check_local_server": check_local_server,
                    "run_creator_mode": run_creator_mode,
                    "project_structure": project_structure,
                    "print_creator_details": _print_creator_details,
                    "run_and_render": lambda old_len: _tui_run(
                        old_len, messages, bridge, (tui_agent_mode[0] or "agent")
                    ),
                    "agent_graph": agent_graph,
                    "refresh_runtime_tools": _refresh_runtime_tools,
                    "mode_state": tui_agent_mode,
                    "set_mode": handle_mode_toggle,
                }

                from Agent.command_router import CommandRouter
                from Agent.command_router._main import _sync_router_model_ctx

                router = CommandRouter(cmd_ctx)
                result = router.handle(user_text)
                _sync_router_model_ctx(cmd_ctx)
                pending_cmd = cmd_ctx.pop("pending_user_input", None)

                if result == "exit":
                    app.call_from_thread(app.exit)
                    return
                if result is True and pending_cmd is None:
                    return
                if pending_cmd is not None:
                    user_text = str(pending_cmd).strip()

                mode = (tui_agent_mode[0] or "agent").lower()
                human_content = user_text
                if mode == "research" and not user_text.strip().lower().startswith("/"):
                    bridge.on_info("🔬 Research mode active")
                    human_content = (
                        "[Research mode — use web_search, web_fetch, multiple sources]\n\n"
                        + user_text
                    )

                display_plain = ((bubble_text or "").strip() or user_text)

                user_turn_idx = sum(1 for m in messages if isinstance(m, HumanMessage))
                try:
                    save_pre_turn_snapshot(session_id, user_turn_idx, list(messages))
                    save_pre_turn_workspace_snapshot(session_id, user_turn_idx)
                except Exception:
                    pass

                messages.append(HumanMessage(content=human_content))
                try:
                    bridge.on_chat_user_message(display_plain, user_turn_idx)
                except Exception:
                    pass
                bridge.on_separator("Round")

                if mode == "creator":
                    bridge.on_agent_start()
                    try:
                        creator_result = run_creator_mode(
                            task=user_text,
                            tools=tools,
                            project_context=project_structure,
                        )
                        summary = format_creator_summary_text(creator_result)
                        est_out = max(1, len(summary) // 3)
                        bridge.on_model_reply(
                            summary,
                            {
                                "prompt_tokens": 0,
                                "completion_tokens": est_out,
                                "_estimated": True,
                            },
                        )
                        messages.append(AIMessage(content=summary))
                    except Exception as ce:
                        bridge.on_error(f"Creator error: {ce}")
                    finally:
                        bridge.on_agent_done()
                elif mode == "deep":
                    bridge.on_agent_start()
                    try:
                        from Agent.deep_solver import run_deep_solver
                        summary = run_deep_solver(
                            task=user_text,
                            tools=tools,
                            bridge=bridge,
                            project_context=project_structure,
                            session_id=session_id,
                            messages=messages,
                        )
                        if summary:
                            messages.append(AIMessage(content=summary))
                            bridge.on_model_reply(
                                summary,
                                {
                                    "prompt_tokens": 0,
                                    "completion_tokens": max(1, len(summary) // 3),
                                    "_estimated": True,
                                },
                            )
                    except Exception as de:
                        bridge.on_error(f"Deep solver error: {de}")
                    finally:
                        bridge.on_agent_done()
                    try:
                        save_state(messages, session_id=session_id)
                    except Exception:
                        pass
                    try:
                        save_state(messages, session_id=session_id)
                        if not title_flag[0]:
                            n_h = sum(1 for m in messages if isinstance(m, HumanMessage))
                            if n_h >= 1:
                                first_u = ""
                                for m in messages:
                                    if isinstance(m, HumanMessage):
                                        first_u = str(m.content or "")
                                        break
                                tit = _tui_generate_session_title(first_u)
                                if tit:
                                    save_state(messages, session_id=session_id, title=tit)
                                    title_flag[0] = True
                    except Exception:
                        pass
                else:
                    _tui_run(len(messages), messages, bridge, mode)

            except Exception as e:
                tb = traceback.format_exc()
                print(f"[Lorne Worker Error] {tb}", file=sys.stderr)
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

    def _tui_run(old_len, msgs, bridge_ref, chat_mode: str = "agent"):
        from Agent.stream_chat_mode import set_stream_chat_mode

        set_stream_chat_mode(chat_mode)
        bridge_ref.clear_stop()
        bridge_ref.on_agent_start()
        try:
            from Agent.message_utils import extract_message_usage
            # last_usage tracks the most recent LLM call's prompt+completion so
            # the context meter reflects actual window fill, not a sum of every
            # tool-loop iteration (which would double-count history).
            last_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            for state in agent_graph.stream({"messages": msgs}, stream_mode="values"):
                if bridge_ref.is_stop_requested():
                    bridge_ref.on_warning("Agent stopped by user")
                    break
                msgs.clear()
                msgs.extend(state["messages"])
                new_msgs = msgs[old_len:]
                for msg in new_msgs:
                    if isinstance(msg, AIMessage):
                        u = extract_message_usage(msg)
                        if u.get("input_tokens") or u.get("output_tokens"):
                            last_usage = u
                            total_used = (
                                u.get("total_tokens")
                                or (u.get("input_tokens", 0) + u.get("output_tokens", 0))
                            )
                            bridge_ref.on_context_update(total_used, CONTEXT_LIMIT)

                        content = str(msg.content or "").strip()
                        usage_out: Dict[str, Any] = {}
                        if u.get("input_tokens") or u.get("output_tokens"):
                            usage_out = {
                                "prompt_tokens": int(u.get("input_tokens", 0)),
                                "completion_tokens": int(u.get("output_tokens", 0)),
                            }
                        if content:
                            try:
                                from Agent.message_utils import extract_thought_segments
                                segs, content = extract_thought_segments(content)
                            except Exception:
                                segs, content = [], content
                            for th in segs:
                                if (th or "").strip():
                                    bridge_ref.on_thought(th.strip())
                            content = (content or "").strip()
                        if content:
                            bridge_ref.on_model_reply(content, usage_out or None)
                old_len = len(msgs)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[Lorne Agent Error] {tb}", file=sys.stderr)
            bridge_ref.on_error(f"Agent error: {type(e).__name__}: {e}")
        finally:
            try:
                if (
                    chat_mode == "brainer"
                    and bridge_ref.is_stop_requested()
                ):
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
            bridge_ref.on_agent_done()

        try:
            save_state(msgs, session_id=session_id)
            if not title_flag[0]:
                n_h = sum(1 for m in msgs if isinstance(m, HumanMessage))
                if n_h >= 1:
                    first_u = ""
                    for m in msgs:
                        if isinstance(m, HumanMessage):
                            first_u = str(m.content or "")
                            break
                    tit = _tui_generate_session_title(first_u)
                    if tit:
                        save_state(msgs, session_id=session_id, title=tit)
                        title_flag[0] = True
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
                # Push the freshly-resolved context window to the UI so
                # the meter shows the real num_ctx of the picked model
                # immediately — otherwise local Ollama models (which
                # often don't return usage stats) would keep displaying
                # the previous model's window until the first assistant
                # reply arrived.
                try:
                    bridge.on_context_update(0, CONTEXT_LIMIT)
                except Exception:
                    pass
                try:

                    def _after_model_switch(mid: str, mname: str, lim: int) -> None:
                        try:
                            app.chat.apply_model_context_limit(mid, lim)
                        except Exception:
                            pass
                        try:
                            app.notify(
                                f"Модель: {mname} · окно ~{lim:,} ток.",
                                timeout=4,
                            )
                        except Exception:
                            pass

                    app.call_from_thread(_after_model_switch, model_id, MODEL_NAME, CONTEXT_LIMIT)
                except Exception:
                    pass
            except Exception as e:
                bridge.on_error(f"Model error: {e}")
        threading.Thread(target=_work, daemon=True).start()

    def handle_mode_toggle(mode: str):
        """Called when user changes the agent mode."""
        mode_lower = (mode or "agent").lower() if isinstance(mode, str) else "agent"
        allowed = ("agent", "ask", "creator", "research", "deep", "brainer")
        if mode_lower not in allowed:
            mode_lower = "agent"
        tui_agent_mode[0] = mode_lower
        creator_mode_active[0] = mode_lower == "creator"
        research_mode_active[0] = mode_lower == "research"
        try:
            _sync_tui_tool_bundle(mode_lower)
        except Exception:
            pass
        try:
            from langchain_core.messages import SystemMessage
            from Agent.prompts import mode_prompt_addon

            frag = mode_prompt_addon(mode_lower)
            if frag:
                messages.append(SystemMessage(content=frag))
        except Exception:
            pass

        if mode_lower == "brainer":
            def _brain_bg() -> None:
                try:
                    from Agent.path_utils import get_project_root
                    from Agent.project_brain import refresh_project_brain
                    from Agent.rag import index_project_brain

                    r = get_project_root().resolve()
                    refresh_project_brain(r)
                    n = index_project_brain(str(r))
                    app.call_from_thread(
                        app.notify,
                        f"Brainer: project brain обновлён ({n} brain-чанков в RAG).",
                    )
                except Exception as e:
                    app.call_from_thread(app.notify, f"Brainer: {e}", severity="error")

            threading.Thread(target=_brain_bg, daemon=True).start()

    def handle_app_close() -> None:
        """Called when TUI is closing: best-effort unload of running Ollama models."""
        try:
            stats = unload_ollama_models(
                base_url=os.getenv("OLLAMA_BASE_URL", ""),
                api_key=os.getenv("OLLAMA_API_KEY", ""),
            )
            if isinstance(stats, dict) and int(stats.get("running") or 0) > 0:
                try:
                    bridge.on_info(
                        "Ollama unload: "
                        f"{int(stats.get('unloaded') or 0)}/{int(stats.get('running') or 0)}",
                    )
                except Exception:
                    pass
        except Exception:
            pass
        mode_lower = (tui_agent_mode[0] or "agent").lower()
        try:
            if mode_lower == "creator":
                app.call_from_thread(
                    app.active_agents.update_creator_tree,
                    {"worker_id": "creator", "status": "working", "task": "Creator mode", "children": []},
                )
            elif mode_lower == "research":
                app.call_from_thread(
                    app.active_agents.update_creator_tree,
                    {
                        "worker_id": "research",
                        "status": "working",
                        "task": "Research mode",
                        "model_type": "research",
                        "children": [{"worker_id": "web-search", "status": "working", "task": "Web + docs"}],
                    },
                )
            elif mode_lower in ("agent", "ask", "deep", "brainer"):
                app.call_from_thread(
                    app.active_agents.update_creator_tree,
                    {"worker_id": mode_lower, "status": "working", "task": f"{mode_lower} mode", "children": []},
                )
            else:
                app.call_from_thread(
                    app.active_agents.update_creator_tree,
                    {"worker_id": "idle", "status": "pending", "task": "No active mode", "children": []},
                )
        except Exception:
            pass

    def handle_deep_checkpoint(cp_id: str, action: str) -> None:
        """Rollback/continue from a Deep Solver checkpoint card."""
        def _work() -> None:
            try:
                from Agent.deep_solver import apply_checkpoint_action
                br = bridge_ref[0]
                res = apply_checkpoint_action(
                    cp_id=cp_id, action=action,
                    messages=messages,
                    enhanced_system_prompt=enhanced_system_prompt,
                    session_id=session_id,
                    bridge=br,
                )
                if not res.get("ok"):
                    if br:
                        br.on_error(f"Deep checkpoint: {res.get('error')}")
                    return
                if br:
                    if action == "continue":
                        label = res.get("checkpoint_title") or f"checkpoint {cp_id[:8]}"
                        br.on_deep_context_chip(cp_id, label)
                        br.on_info(
                            f"Продолжаем с чекпоинта «{label}» — задай следующий шаг."
                        )
                    else:
                        br.on_info("Откат к чекпоинту выполнен.")
            except Exception as e:
                br = bridge_ref[0]
                if br:
                    br.on_error(f"Deep checkpoint error: {e}")

        threading.Thread(target=_work, daemon=True).start()

    app = LorneApp(
        model_name=MODEL_NAME,
        branch=git_branch,
        models=get_available_models(),
        on_chat_submit=handle_chat_submit,
        on_model_change=handle_model_change,
        on_mode_toggle=handle_mode_toggle,
        on_session_resolved=apply_session_pick,
        on_chat_rollback=handle_rollback,
        on_app_close=handle_app_close,
        on_deep_checkpoint=handle_deep_checkpoint,
    )
    bridge = TUIBridge(app)
    bridge_ref[0] = bridge
    app.set_bridge(bridge)
    set_bridge(bridge)

    app.run()
    set_bridge(None)


if __name__ == "__main__":
    mode = env_pref("MODE", "tui").lower()
    if mode == "classic":
        run_coding_agent_loop()
    else:
        run_tui_mode()
