"""CLI command router — handles all /slash commands from the main loop."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage

try:
    from Interface.visualization import (
        display_shell_command, display_tool_result, display_model_selector,
        display_status_panel, display_rag_results, display_enhanced_status,
        suggest_command,
        print_info, print_success, print_warning, print_error, print_commands,
        get_user_input, console, HAS_RICH,
    )
except ImportError:
    def display_shell_command(cmd): print(f"  $ {cmd}")
    def display_tool_result(sn, name, result): print(f"  Result: {name}")
    def display_model_selector(m, c): pass
    def display_status_panel(*a): pass
    def display_rag_results(r, q): pass
    def display_enhanced_status(*a, **kw): pass
    def suggest_command(s): return None
    def print_info(m): print(f"  {m}")
    def print_success(m): print(f"  ✓ {m}")
    def print_warning(m): print(f"  ⚠ {m}")
    def print_error(m): print(f"  ✗ {m}")
    def print_commands(): print("  /help, /exit")
    def get_user_input():
        try: return input("> ")
        except: return "/exit"
    console = None
    HAS_RICH = False

from .tool_registry import (
    list_files, save_plan, load_plan, update_plan, clear_plan,
    list_custom_tools, add_custom_tool, remove_custom_tool,
    reload_tools, get_custom_tools_prompt,
)


def _should_autoplan(text: str) -> bool:
    if not (text or "").strip():
        return False
    low = text.lower()
    skip_patterns = [
        "привет", "hello", "hi ", "что ты", "кто ты", "who are",
        "спасибо", "thanks", "ok", "понял", "ладно",
    ]
    if any(p in low for p in skip_patterns):
        return False
    if len(text.split()) < 4:
        return False
    return True


class CommandRouter:
    """Dispatches /slash commands. Returns True if the command was handled."""

    def __init__(self, ctx: Dict[str, Any]):
        """ctx keys: messages, session_id, tools, _base_tools, model_name,
        model_profile, context_limit, resolve_abs_path, analyze_project_structure,
        init_llm, get_available_profiles, AVAILABLE_MODELS, set_model,
        fetch_openrouter_credits, format_credits_info, save_state,
        creator_mode_active, get_creator_config, save_creator_config,
        check_local_server, run_creator_mode, project_structure,
        print_creator_details, agent_graph.
        """
        self.ctx = ctx

    def handle(self, user_input: str) -> Optional[bool]:
        """Handle a command. Returns True if handled, None if not a command."""
        low = user_input.lower()

        if low in ("/exit", "exit", "quit", "q"):
            print_info("До встречи!")
            return "exit"

        if low in ("/help", "help"):
            print_commands()
            return True

        if user_input.startswith("!"):
            return self._handle_shell(user_input)

        if low.startswith("/ls"):
            return self._handle_ls(user_input)

        if low.startswith("/tree"):
            return self._handle_tree(user_input)

        if low.startswith("/plan"):
            return self._handle_plan()

        if low.startswith("/status"):
            return self._handle_status()

        if low.startswith("/profile"):
            return self._handle_profile(user_input)

        if low.startswith("/model"):
            return self._handle_model(user_input)

        if low.startswith("/balance") or low.startswith("/credits"):
            return self._handle_balance()

        if low.startswith("/compact"):
            return self._handle_compact()

        if low.startswith("/versions"):
            return self._handle_versions(user_input)

        if low.startswith("/rollback"):
            return self._handle_rollback(user_input)

        if low.startswith("/agent"):
            return self._handle_agent(user_input)

        if low.startswith("/custom"):
            return self._handle_custom(user_input)

        if low.startswith("/creator"):
            return self._handle_creator(user_input)

        if low.startswith("/research"):
            return self._handle_research(user_input)

        if low.startswith("/rag"):
            return self._handle_rag(user_input)

        if low.startswith("/git"):
            return self._handle_git(user_input)

        # Suggest command if looks like a mistyped /command
        if user_input.startswith("/"):
            suggestion = suggest_command(user_input)
            if suggestion:
                print_warning(f"Неизвестная команда. Возможно, вы имели в виду: {suggestion}")
                return True

        return None

    # ─── Individual command handlers ────────────────────────────

    def _handle_shell(self, user_input: str) -> bool:
        cmd = user_input[1:].strip()
        if not cmd:
            print_warning("Использование: !<команда>  (например: !ls -la, !git status)")
            return True
        display_shell_command(cmd)
        from Terminal.runner import run_command_safe
        result = run_command_safe(command=cmd, timeout=60)
        display_tool_result(0, "run_command", result)
        return True

    def _handle_ls(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        p = parts[1].strip() if len(parts) > 1 else "."
        try:
            listing = list_files.invoke({"path": p, "recursive": False, "pattern": "*"})
            display_tool_result(0, "list_files", listing)
        except Exception as e:
            print_error(f"/ls: {e}")
        return True

    def _handle_tree(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        p = parts[1].strip() if len(parts) > 1 else "."
        try:
            resolve = self.ctx["resolve_abs_path"]
            analyze = self.ctx["analyze_project_structure"]
            root = resolve(p)
            tree = analyze(root)
            if HAS_RICH and console:
                from rich.panel import Panel
                from rich import box as rbox
                console.print(Panel(tree, title="Project Tree", border_style="cyan", box=rbox.ROUNDED))
            else:
                print(tree)
        except Exception as e:
            print_error(f"/tree: {e}")
        return True

    def _handle_plan(self) -> bool:
        try:
            result = load_plan.invoke({})
            from Interface.visualization import display_tool_result as _dtr
            _dtr(0, "load_plan", result)
        except Exception as e:
            print_error(f"/plan: {e}")
        return True

    def _handle_status(self) -> bool:
        messages = self.ctx["messages"]
        human_count = len([m for m in messages if isinstance(m, HumanMessage)])
        ai_count = len([m for m in messages if isinstance(m, AIMessage)])
        from langchain_core.messages import ToolMessage
        tool_count = len([m for m in messages if isinstance(m, ToolMessage)])

        rag_stats = None
        try:
            from Agent.rag import get_index_stats
            rag_stats = get_index_stats()
        except Exception:
            pass

        creator_active = self.ctx.get("creator_mode_active", [False])[0]
        research_active = self.ctx.get("research_mode_active", [False])[0]

        display_enhanced_status(
            self.ctx["model_name"], self.ctx["model_profile"],
            self.ctx["context_limit"],
            human_count, ai_count, tool_count, len(messages),
            rag_stats=rag_stats,
            creator_active=creator_active,
            research_active=research_active,
        )
        return True

    def _handle_profile(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        if len(parts) == 1:
            print_info(f"Текущий: {self.ctx['model_profile']} ({self.ctx['model_name']})")
            profiles = self.ctx["get_available_profiles"]()
            print_info(f"Доступные: {', '.join(sorted(profiles.keys()))}")
            return True
        new_profile = parts[1].strip()
        self.ctx["init_llm"](new_profile)
        print_success(f"Переключено на: {self.ctx['model_profile']} ({self.ctx['model_name']})")
        return True

    def _handle_model(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        models = self.ctx["AVAILABLE_MODELS"]
        set_model_fn = self.ctx["set_model"]
        init_llm = self.ctx["init_llm"]

        if len(parts) > 1 and parts[1].strip():
            custom_model = parts[1].strip()
            set_model_fn(custom_model)
            init_llm()
            print_success(f"Модель установлена: {self.ctx['model_name']}")
            print_info("Выбор сохранён и будет использоваться при следующем запуске")
            return True

        display_model_selector(models, self.ctx["model_name"])

        try:
            from simple_term_menu import TerminalMenu
            model_options = [f"{m['name']} ({m['id']})" for m in models]
            current_idx = 0
            for idx, m in enumerate(models):
                if m["id"] == self.ctx["model_name"]:
                    current_idx = idx
                    break
            terminal_menu = TerminalMenu(
                model_options,
                title="Выберите модель (Esc для отмены):",
                cursor_index=current_idx,
                clear_screen=False,
            )
            menu_entry_index = terminal_menu.show()
            if menu_entry_index is not None:
                chosen = models[menu_entry_index]["id"]
                set_model_fn(chosen)
                init_llm()
                print_success(f"Модель: {self.ctx['model_name']}")
                print_info("Выбор сохранён")
            return True
        except (ImportError, Exception):
            pass

        try:
            choice = get_user_input().strip()
        except (EOFError, KeyboardInterrupt):
            return True
        if not choice:
            return True
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                chosen = models[idx]["id"]
                set_model_fn(chosen)
                init_llm()
                print_success(f"Модель: {self.ctx['model_name']}")
                print_info("Выбор сохранён")
            else:
                print_error(f"Неверный номер. Введи 1-{len(models)}")
        else:
            set_model_fn(choice)
            init_llm()
            print_success(f"Модель: {self.ctx['model_name']}")
            print_info("Выбор сохранён")
        return True

    def _handle_balance(self) -> bool:
        print_info("Запрос баланса OpenRouter…")
        creds = self.ctx["fetch_openrouter_credits"]()
        if creds is None:
            print_error("Не удалось получить данные. Проверь OPENROUTER_API_KEY.")
        else:
            info = self.ctx["format_credits_info"](creds)
            if HAS_RICH and console:
                from rich.panel import Panel as RPanel
                from rich import box as rbox
                console.print(RPanel(
                    info,
                    title="[bold]OpenRouter — Счёт[/bold]",
                    border_style="green",
                    box=rbox.ROUNDED,
                    padding=(1, 2),
                ))
            else:
                print_info("═ OpenRouter — Счёт ═")
                for line in info.split("\n"):
                    print_info(f"  {line}")
        return True

    def _handle_compact(self) -> bool:
        from .message_utils import compact_conversation
        messages = self.ctx["messages"]
        before = len(messages)
        compacted = compact_conversation(messages, keep_last=12)
        messages.clear()
        messages.extend(compacted)
        after = len(messages)
        if before != after:
            print_success(f"Сжато: {before} → {after} сообщений")
            try:
                self.ctx["save_state"](messages, session_id=self.ctx["session_id"])
            except Exception:
                pass
        else:
            print_info("Разговор уже компактный")
        return True

    def _handle_versions(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            print_warning("Использование: /versions <путь>")
            return True
        p = parts[1].strip()
        messages = self.ctx["messages"]
        messages.append(HumanMessage(content=f"Show file versions using list_file_versions(path='{p}')."))
        self.ctx["run_and_render"](len(messages))
        return True

    def _handle_rollback(self, user_input: str) -> bool:
        parts = user_input.split()
        if len(parts) < 2:
            print_warning("Использование: /rollback <путь> [version_id]")
            return True
        p = parts[1].strip()
        vid = parts[2].strip() if len(parts) >= 3 else ""
        messages = self.ctx["messages"]
        messages.append(HumanMessage(content=f"Rollback file using rollback_file(path='{p}', version_id='{vid}')."))
        self.ctx["run_and_render"](len(messages))
        return True

    def _handle_agent(self, user_input: str) -> bool:
        from Agent.multiagent import list_agents, set_current_agent
        parts = user_input.split()
        if len(parts) == 1 or parts[1] == "list":
            print_info("Под-агенты:")
            for a in list_agents():
                print_info(f"  - {a.get('id')}: {a.get('title')}")
            if self.ctx.get("research_mode_active", [False])[0]:
                print_info("  - research: Режим исследования (web/doc tools)")
            return True
        if parts[1] == "use" and len(parts) >= 3:
            aid = set_current_agent(parts[2])
            print_success(f"Текущий под-агент: {aid}")
            return True
        print_warning("Использование: /agent list | /agent use <id>")
        return True

    def _handle_git(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=2)
        subcmd = parts[1].strip().lower() if len(parts) > 1 else ""
        arg = parts[2].strip() if len(parts) > 2 else ""

        try:
            from Agent.git_integration import get_git_manager
            gm = get_git_manager()
        except ImportError:
            print_error("GitPython не установлен. pip install gitpython")
            return True

        if not gm.available:
            print_error("Git не инициализирован в этом проекте")
            return True

        if not subcmd or subcmd == "status":
            status = gm.status_summary()
            print_info(f"Ветка: {status.get('branch', 'N/A')}")
            if status.get("clean"):
                print_success("Рабочая директория чистая")
            else:
                for cat, label in [("changed", "Изменены"), ("staged", "Staged"), ("untracked", "Untracked")]:
                    files = status.get(cat, [])
                    if files:
                        print_info(f"  {label}:")
                        for f in files[:10]:
                            print_info(f"    - {f}")
            return True

        if subcmd == "log":
            commits = gm.log(path=arg or None, limit=15)
            if not commits:
                print_info("Нет коммитов")
                return True
            if HAS_RICH and console:
                from rich.table import Table as RTable
                from rich import box as rbox
                table = RTable(title="[bold]Git Log[/bold]", box=rbox.ROUNDED,
                               border_style="cyan", padding=(0, 1))
                table.add_column("Hash", style="bold yellow", width=10)
                table.add_column("Сообщение", style="white")
                table.add_column("Дата", style="dim", width=20)
                table.add_column("Файлов", style="dim", width=7, justify="right")
                for c in commits:
                    table.add_row(c["hash"], c["message"][:60], c["date"][:19], str(c["files_changed"]))
                console.print(table)
            else:
                for c in commits:
                    print_info(f"  {c['hash']}  {c['message'][:50]}  ({c['date'][:10]})")
            return True

        if subcmd == "diff":
            diff_text = gm.diff(commit_hash=arg or None)
            if not diff_text.strip():
                print_info("Нет изменений")
            else:
                if HAS_RICH and console:
                    from rich.syntax import Syntax
                    from rich.panel import Panel as RPanel
                    from rich import box as rbox
                    console.print(RPanel(
                        Syntax(diff_text[:5000], "diff", theme="monokai"),
                        title="[bold]Git Diff[/bold]",
                        border_style="yellow", box=rbox.ROUNDED,
                    ))
                else:
                    for line in diff_text[:3000].splitlines():
                        print(f"  {line}")
            return True

        if subcmd == "rollback" and arg:
            result = gm.rollback_commit(arg)
            if result.get("ok"):
                print_success(f"Коммит {arg} отменён")
            else:
                print_error(f"Ошибка: {result.get('error')}")
            return True

        if subcmd == "branch":
            print_info(f"Текущая ветка: {gm.current_branch()}")
            return True

        print_warning("Использование: /git [status|log|diff|rollback|branch]")
        return True

    def _handle_research(self, user_input: str) -> bool:
        """Research command: /research on|off|status|<query>."""
        parts = user_input.split(maxsplit=1)
        query = parts[1].strip() if len(parts) > 1 else ""
        q_low = query.lower()
        research_flag = self.ctx.get("research_mode_active")

        if q_low in ("on", "enable"):
            if isinstance(research_flag, list):
                research_flag[0] = True
            print_success("Research mode: ON")
            return True

        if q_low in ("off", "disable"):
            if isinstance(research_flag, list):
                research_flag[0] = False
            print_info("Research mode: OFF")
            return True

        if q_low in ("status",):
            active = bool(research_flag[0]) if isinstance(research_flag, list) else False
            print_info(f"Research mode: {'ON' if active else 'OFF'}")
            return True

        if not query:
            print_warning("Usage: /research on|off|status|<topic or question>")
            return True

        print_info(f"🔍 Research mode: {query[:80]}")
        print_info("Using web search, context7, and orchestrator for deep analysis…")

        messages = self.ctx["messages"]
        research_prompt = (
            f"RESEARCH MODE — Deep Analysis Task\n\n"
            f"Topic: {query}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Use web_search() to find current information about this topic\n"
            f"2. Use multiple search queries to cover different angles\n"
            f"3. If relevant, use context7_search() for library documentation\n"
            f"4. Analyze and synthesize all findings\n"
            f"5. Present a comprehensive, well-structured report\n\n"
            f"You MUST use internet/web search tools. Do NOT rely solely on your training data.\n"
            f"Search at least 3-5 different queries to build a complete picture.\n"
            f"Include sources and links where possible.\n"
            f"Write the final report in the user's language."
        )
        messages.append(HumanMessage(content=research_prompt))
        self.ctx["run_and_render"](len(messages))
        return True

    def _handle_rag(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            print_warning("Использование: /rag <запрос>")
            return True
        query_text = parts[1].strip()
        try:
            from Agent.rag import query as rag_query, get_index_stats
            results = rag_query(query_text, top_k=10)
            display_rag_results(results, query_text)
            stats = get_index_stats()
            print_info(f"Индекс: {stats.get('chunks', 0)} чанков, {stats.get('files', 0)} файлов")
        except Exception as e:
            print_error(f"/rag: {e}")
        return True

    def _handle_custom(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=2)
        subcmd = parts[1].strip().lower() if len(parts) > 1 else ""
        tools = self.ctx["tools"]
        refresh_runtime_tools = self.ctx.get("refresh_runtime_tools")

        if not subcmd or subcmd == "list":
            items = list_custom_tools()
            if not items:
                print_info("Кастомных тулов нет. Добавь: /custom add <имя>")
            else:
                if HAS_RICH and console:
                    from rich.table import Table as RTable
                    from rich import box as rbox
                    table = RTable(
                        title="[bold]Custom Tools[/bold]",
                        box=rbox.ROUNDED, border_style="magenta", padding=(0, 1),
                    )
                    table.add_column("Имя", style="bold cyan")
                    table.add_column("Описание", style="dim")
                    for item in items:
                        table.add_row(item["name"], item["description"])
                    console.print(table)
                else:
                    print_info("Custom Tools:")
                    for item in items:
                        print_info(f"  - {item['name']}: {item['description']}")
            return True

        if subcmd == "add":
            tool_name = parts[2].strip() if len(parts) > 2 else ""
            if not tool_name:
                print_warning("Использование: /custom add <имя_тула>")
                return True
            print_info(f"Введи код тула '{tool_name}' (используй @tool декоратор).")
            print_info("Пустая строка + Enter = завершить ввод. Или Enter сразу = создать шаблон.")
            code_lines = []
            while True:
                try:
                    line = input("... ")
                except (EOFError, KeyboardInterrupt):
                    break
                if not line and not code_lines:
                    break
                if not line and code_lines:
                    break
                code_lines.append(line)
            code = "\n".join(code_lines) if code_lines else None
            result = add_custom_tool(tool_name, code=code)
            if result.get("ok"):
                print_success(f"Тул '{tool_name}' создан: {result.get('path')}")
                if result.get("warning"):
                    print_warning(result["warning"])
                custom_new = reload_tools(tools)
                if callable(refresh_runtime_tools):
                    refresh_runtime_tools()
                print_info(f"Тулы перезагружены: {len(tools)} всего")
            else:
                print_error(f"Ошибка: {result.get('error')}")
            return True

        if subcmd in ("remove", "rm"):
            tool_name = parts[2].strip() if len(parts) > 2 else ""
            if not tool_name:
                print_warning("Использование: /custom remove <имя_тула>")
                return True
            result = remove_custom_tool(tool_name)
            if result.get("ok"):
                print_success(f"Тул '{result.get('removed')}' удалён")
                reload_tools(tools)
                if callable(refresh_runtime_tools):
                    refresh_runtime_tools()
                print_info(f"Тулы перезагружены: {len(tools)} всего")
            else:
                print_error(f"Ошибка: {result.get('error')}")
            return True

        if subcmd == "reload":
            custom_new = reload_tools(tools)
            if callable(refresh_runtime_tools):
                refresh_runtime_tools()
            print_success(f"Custom tools перезагружены: {len(custom_new)} кастомных, {len(tools)} всего")
            return True

        print_warning("Использование: /custom [list|add|remove|reload]")
        return True

    def _handle_creator(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        subcmd = parts[1].strip() if len(parts) > 1 else ""
        subcmd_low = subcmd.lower()

        if not subcmd or subcmd_low == "on":
            self.ctx["creator_mode_active"][0] = True
            print_success("Creator Mode активирован")
            print_info("Следующие задачи будут выполняться параллельными агентами")
            creator_cfg = self.ctx["get_creator_config"]()
            print_info(f"  Локальная модель: {creator_cfg['local_model']}")
            print_info(f"  Сервер: {creator_cfg['local_base_url']}")
            print_info(f"  Макс. воркеров: {creator_cfg['max_workers']}")
            local_ok = self.ctx["check_local_server"](creator_cfg['local_base_url'])
            if local_ok:
                print_success("  Локальный сервер: доступен ✓")
            else:
                print_warning("  Локальный сервер: недоступен (будет fallback на heavy)")
            return True

        if subcmd_low == "off":
            self.ctx["creator_mode_active"][0] = False
            print_info("Creator Mode деактивирован")
            return True

        if subcmd_low == "config":
            creator_cfg = self.ctx["get_creator_config"]()
            if HAS_RICH and console:
                from rich.panel import Panel as CPanel
                from rich import box as rbox
                local_ok = self.ctx["check_local_server"](creator_cfg['local_base_url'])
                status_str = "[green]✓ доступен[/green]" if local_ok else "[red]✗ недоступен[/red]"
                content = (
                    f"  [dim]Локальная модель:[/dim]  [bold]{creator_cfg['local_model']}[/bold]\n"
                    f"  [dim]Сервер:[/dim]           [bold]{creator_cfg['local_base_url']}[/bold]\n"
                    f"  [dim]Статус:[/dim]           {status_str}\n"
                    f"  [dim]Макс. воркеров:[/dim]   [bold]{creator_cfg['max_workers']}[/bold]\n"
                    f"  [dim]Активен:[/dim]          [bold]{'Да' if creator_cfg['enabled'] or self.ctx['creator_mode_active'][0] else 'Нет'}[/bold]"
                )
                console.print(CPanel(
                    content,
                    title="[bold]⚡ Creator Mode — Конфигурация[/bold]",
                    border_style="magenta", box=rbox.ROUNDED, padding=(1, 2),
                ))
            else:
                print_info("Creator Mode — Конфигурация:")
                for k, v in creator_cfg.items():
                    print_info(f"  {k}: {v}")
            return True

        if subcmd_low.startswith("set "):
            set_parts = subcmd.split(maxsplit=2)
            if len(set_parts) < 3:
                print_warning("Использование: /creator set <параметр> <значение>")
                print_info("  Параметры: local_model, local_base_url, max_workers")
                return True
            param = set_parts[1].strip().lower()
            value = set_parts[2].strip()
            valid_params = {"local_model", "local_base_url", "max_workers"}
            if param not in valid_params:
                print_warning(f"Неизвестный параметр: {param}. Допустимые: {', '.join(valid_params)}")
                return True
            if param == "max_workers":
                try:
                    value = int(value)
                except ValueError:
                    print_error("max_workers должен быть числом")
                    return True
            self.ctx["save_creator_config"]({param: value})
            print_success(f"Creator: {param} = {value}")
            return True

        if subcmd:
            self._run_creator_task(subcmd)
            return True

        return True

    def _run_creator_task(self, task: str) -> None:
        """Execute a task through Creator Mode."""
        print_info(f"Запуск Creator Mode: {task[:80]}")
        creator_result = self.ctx["run_creator_mode"](
            task=task,
            tools=self.ctx["tools"],
            project_context=self.ctx["project_structure"],
        )
        self.ctx["print_creator_details"](creator_result)

        messages = self.ctx["messages"]
        summary_parts = [f"Creator Mode выполнил задачу: {task}"]
        for r in creator_result.get("results", []):
            status_icon = "✓" if r["status"] == "done" else "✗"
            summary_parts.append(f"  {status_icon} {r['worker_id']}: {r['task'][:60]}")
            if r.get("result"):
                summary_parts.append(f"    Результат: {r['result']}")
        summary_text = "\n".join(summary_parts)
        messages.append(HumanMessage(content=f"[Creator Mode результат]\n{summary_text}"))
        messages.append(AIMessage(content=summary_text))
        try:
            self.ctx["save_state"](messages, session_id=self.ctx["session_id"])
        except Exception:
            pass
