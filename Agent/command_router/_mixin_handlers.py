"""Маршрутизатор slash-команд (classic CLI и воркер TUI). Возврат: обработано / не команда / exit."""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage

try:
    from Interface.visualization import (
        display_shell_command, display_tool_result, display_model_selector,
        display_status_panel, display_rag_results, display_enhanced_status,
        display_model_reply,
        suggest_command,
        print_info, print_info_block, print_success, print_warning, print_error, print_commands, print_help_topic,
        get_user_input, read_cli_line, console, HAS_RICH,
    )
except ImportError:
    def display_shell_command(cmd): print(f"  $ {cmd}")
    def display_tool_result(sn, name, result): print(f"  Result: {name}")
    def display_model_selector(m, c): pass
    def display_status_panel(*a): pass
    def display_rag_results(r, q): pass
    def display_enhanced_status(*a, **kw): pass
    def display_model_reply(sn, content, meta=None):
        if content:
            print((content or "").strip()[:8000])
    def suggest_command(s): return None
    def print_info(m): print(f"  {m}")
    def print_info_block(lines, title="Инфо", accent="dim"):
        if isinstance(lines, str):
            print_info(lines)
        else:
            for ln in (lines or [""]): print(f"  {ln}")
    def print_success(m): print(f"  ✓ {m}")
    def print_warning(m): print(f"  ⚠ {m}")
    def print_error(m): print(f"  ✗ {m}")
    def print_commands(): print("  /help, /exit")
    def print_help_topic(t): print_commands()
    def get_user_input():
        try: return input("> ")
        except: return "/exit"
    def read_cli_line(prompt="> "):
        try: return (input(prompt) or "").strip()
        except: return ""
    console = None
    HAS_RICH = False

try:
    from Agent.tool_registry import (
        list_files, save_plan, load_plan, update_plan, clear_plan, plan_tool,
        list_custom_tools, add_custom_tool, remove_custom_tool,
        reload_tools, get_custom_tools_prompt,
    )
    from Agent.creator_summary import format_creator_summary_text
except ImportError:
    from tool_registry import (
        list_files, save_plan, load_plan, update_plan, clear_plan, plan_tool,
        list_custom_tools, add_custom_tool, remove_custom_tool,
        reload_tools, get_custom_tools_prompt,
    )
    from creator_summary import format_creator_summary_text

class CommandRouterMixin:
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

    def _handle_stop(self) -> bool:
        stop_flag = self.ctx.get("stop_requested")
        if isinstance(stop_flag, list) and stop_flag:
            stop_flag[0] = True
            print_warning("Запрошена остановка текущего выполнения")
            return True
        print_warning("Остановка недоступна в этом режиме")
        return True

    def _handle_deep_checkpoint(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=2)
        sub = parts[1].strip().lower() if len(parts) > 1 else "help"
        if sub == "list":
            getter = self.ctx.get("get_deep_checkpoints")
            rows = getter() if callable(getter) else []
            if not rows:
                print_info("Нет активных Deep checkpoint'ов")
                return True
            print_info("Deep checkpoints:")
            for row in rows[:20]:
                print_info(f"  - {row.get('id')}  turn={row.get('turn_index')}  {row.get('title')}")
            return True
        if sub in ("rollback", "continue"):
            cp_id = parts[2].strip() if len(parts) > 2 else ""
            if not cp_id:
                print_warning("Использование: /deepcp rollback <checkpoint_id> | /deepcp continue <checkpoint_id>")
                return True
            applier = self.ctx.get("apply_deep_checkpoint")
            if not callable(applier):
                print_error("Deep checkpoint API недоступен")
                return True
            res = applier(cp_id, sub)
            if isinstance(res, dict) and res.get("ok"):
                print_success(f"Deep checkpoint {sub}: {cp_id}")
            else:
                print_error(f"Deep checkpoint error: {res.get('error') if isinstance(res, dict) else res}")
            return True
        print_warning("Использование: /deepcp list | /deepcp rollback <id> | /deepcp continue <id>")
        return True

    def _handle_ollama(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=3)
        sub = parts[1].strip().lower() if len(parts) > 1 else "help"
        try:
            from Interface.ui_prefs import load_prefs, save_prefs
            from Agent.llm_provider import fetch_ollama_models, fetch_ollama_running_models
        except Exception as e:
            print_error(f"/ollama unavailable: {e}")
            return True

        prefs = load_prefs()
        base_url = str(prefs.get("ollama_base_url") or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1")
        api_key = str(prefs.get("ollama_api_key") or os.getenv("OLLAMA_API_KEY") or "")

        if sub in ("help", "menu"):
            print_info_block(
                [
                    "  /ollama pick          — выбрать модель с сервера (то же, что /model ollama)",
                    "  /ollama status | list | refresh",
                    "  /ollama set-url <url> | /ollama set-key <key>",
                    "  /ollama add-model <name>  | /ollama remove-model <name>",
                    "  /ollama preset-list | /ollama preset-set <model> <preset>",
                    "  /ollama model-set <model> <k=v,...>",
                ],
                title="Ollama команды",
                accent="accent",
            )
            return True

        if sub == "status":
            rows = fetch_ollama_running_models(base_url=base_url, api_key=api_key)
            print_info(f"Ollama URL: {base_url}")
            print_info(f"Running models: {len(rows)}")
            for name in rows[:12]:
                print_info(f"  - {name}")
            return True

        if sub == "list":
            rows = fetch_ollama_models(base_url=base_url, api_key=api_key)
            if not rows:
                print_warning("Ollama модели не найдены")
                return True
            for m in rows[:50]:
                print_info(f"  - {m.get('name')} (ctx {int(m.get('ctx') or 0):,})")
            return True

        if sub == "set-url":
            val = parts[2].strip() if len(parts) > 2 else ""
            if not val:
                print_warning("Использование: /ollama set-url <url>")
                return True
            os.environ["OLLAMA_BASE_URL"] = val
            save_prefs(ollama_base_url=val)
            print_success(f"OLLAMA_BASE_URL = {val}")
            return True

        if sub == "set-key":
            val = parts[2].strip() if len(parts) > 2 else ""
            os.environ["OLLAMA_API_KEY"] = val
            save_prefs(ollama_api_key=val)
            print_success("OLLAMA_API_KEY обновлен")
            return True

        if sub == "refresh":
            rows = fetch_ollama_models(base_url=base_url, api_key=api_key)
            print_success(f"Обновлено. Найдено моделей: {len(rows)}")
            return True

        if sub in ("pick", "select", "use", "choose"):
            return self._ollama_pick_interactive()

        if sub == "add-model":
            name = parts[2].strip() if len(parts) > 2 else ""
            if not name:
                print_warning("Использование: /ollama add-model <name> [ctx]")
                return True
            ctx_val = 32768
            if len(parts) > 3:
                try:
                    ctx_val = int(parts[3].strip())
                except Exception:
                    ctx_val = 32768
            cur = [m for m in (prefs.get("ollama_custom_models") or []) if isinstance(m, dict)]
            cur = [m for m in cur if str(m.get("name") or "") != name]
            cur.append({"name": name, "label": f"Ollama · {name}", "ctx": ctx_val})
            save_prefs(ollama_custom_models=cur)
            print_success(f"Добавлена Ollama модель: {name}")
            return True

        if sub == "remove-model":
            name = parts[2].strip() if len(parts) > 2 else ""
            if not name:
                print_warning("Использование: /ollama remove-model <name>")
                return True
            cur = [m for m in (prefs.get("ollama_custom_models") or []) if isinstance(m, dict)]
            cur = [m for m in cur if str(m.get("name") or "") != name]
            settings = prefs.get("ollama_model_settings") if isinstance(prefs.get("ollama_model_settings"), dict) else {}
            settings.pop(name, None)
            save_prefs(ollama_custom_models=cur, ollama_model_settings=settings)
            print_success(f"Удалена Ollama модель: {name}")
            return True

        if sub == "preset-list":
            presets = prefs.get("ollama_presets") if isinstance(prefs.get("ollama_presets"), dict) else {}
            print_info("Ollama presets:")
            for k in sorted(presets.keys()):
                print_info(f"  - {k}")
            return True

        if sub == "preset-set":
            if len(parts) < 4:
                print_warning("Использование: /ollama preset-set <model> <preset>")
                return True
            model_name = parts[2].strip()
            preset_name = parts[3].strip()
            presets = prefs.get("ollama_presets") if isinstance(prefs.get("ollama_presets"), dict) else {}
            if preset_name not in presets:
                print_error(f"Preset не найден: {preset_name}")
                return True
            mapping = prefs.get("ollama_model_settings") if isinstance(prefs.get("ollama_model_settings"), dict) else {}
            values = dict(presets.get(preset_name) or {})
            mapping[model_name] = {"preset": preset_name, **values}
            save_prefs(ollama_model_settings=mapping)
            print_success(f"Для {model_name} установлен preset {preset_name}")
            return True

        if sub == "model-set":
            if len(parts) < 4:
                print_warning("Использование: /ollama model-set <model> <key=value,...>")
                return True
            model_name = parts[2].strip()
            raw = parts[3].strip()
            mapping = prefs.get("ollama_model_settings") if isinstance(prefs.get("ollama_model_settings"), dict) else {}
            prev = mapping.get(model_name) if isinstance(mapping.get(model_name), dict) else {}
            row = dict(prev)
            for chunk in [c.strip() for c in raw.split(",") if c.strip()]:
                if "=" not in chunk:
                    continue
                key, val = chunk.split("=", 1)
                k = key.strip()
                v = val.strip()
                if k in ("temperature", "top_p", "repeat_penalty"):
                    try:
                        row[k] = float(v)
                    except Exception:
                        continue
                elif k in ("top_k", "num_ctx", "num_predict"):
                    try:
                        row[k] = int(v)
                    except Exception:
                        continue
                elif k in ("stop", "preset"):
                    row[k] = v
            mapping[model_name] = row
            save_prefs(ollama_model_settings=mapping)
            print_success(f"Обновлены настройки модели {model_name}")
            return True

        print_warning(
            "Использование: /ollama [pick|status|list|…]  |  выбор модели: /ollama pick  или  /model ollama"
        )
        return True

    def _handle_theme(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        sub = parts[1].strip() if len(parts) > 1 else ""
        if not sub:
            try:
                from Interface.cli_theme import ALL_CLI_THEME_IDS

                print_info("Темы CLI (свои пресеты, не TUI): " + ", ".join(ALL_CLI_THEME_IDS))
                print_info("Пример: /theme ocean   |   список: /theme list")
            except Exception:
                print_warning("Использование: /theme <id>")
            return True
        if sub.lower() in ("list", "ls", "help"):
            try:
                from Interface.cli_theme import ALL_CLI_THEME_IDS

                print_info("Доступные темы CLI: " + ", ".join(ALL_CLI_THEME_IDS))
            except Exception:
                pass
            return True
        raw = sub
        name = raw
        try:
            from Interface.cli_theme import ALL_CLI_THEME_IDS, resolve_cli_theme_name
            from Interface.ui_prefs import save_prefs
            from Interface.visualization import refresh_cli_ui_from_prefs

            name = resolve_cli_theme_name(raw)
            save_prefs(cli_theme=name)
            refresh_cli_ui_from_prefs(force=True)
            hint = f" (всего пресетов: {len(ALL_CLI_THEME_IDS)})"
        except Exception:
            hint = ""
        print_success(f"Тема CLI: {name}{hint}")
        return True

    def _handle_accent(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            print_warning("Использование: /accent <цвет|#hex|F номер>")
            return True
        value = parts[1].strip()
        normalized = value
        ansi_map = {
            "f1": "#8B5CF6",
            "f2": "#10B981",
            "f3": "#F59E0B",
            "f4": "#EF4444",
            "f5": "#3B82F6",
            "f6": "#A78BFA",
            "f7": "#22C55E",
            "f8": "#F97316",
        }
        key = value.lower().strip()
        if key in ansi_map:
            normalized = ansi_map[key]
        try:
            from Interface.ui_prefs import save_prefs
            from Interface.visualization import refresh_cli_ui_from_prefs

            save_prefs(cli_accent_color=normalized)
            refresh_cli_ui_from_prefs(force=True)
        except Exception:
            pass
        print_success(f"Акцент CLI сохранён: {normalized}")
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
            set_mode = self.ctx.get("set_mode")
            if callable(set_mode):
                set_mode("research")
            print_success("Research mode: ON")
            return True

        if q_low in ("off", "disable"):
            if isinstance(research_flag, list):
                research_flag[0] = False
            set_mode = self.ctx.get("set_mode")
            if callable(set_mode):
                set_mode("agent")
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
            set_mode = self.ctx.get("set_mode")
            if callable(set_mode):
                set_mode("creator")
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
            set_mode = self.ctx.get("set_mode")
            if callable(set_mode):
                set_mode("agent")
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
                    f"  [dim]Оркестрация:[/dim]     [bold]{creator_cfg.get('orchestration', 'parallel')}[/bold]\n"
                    f"  [dim]parallel|sequential|supervisor|hierarchical[/dim]\n"
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
            valid_params = {"local_model", "local_base_url", "max_workers", "orchestration"}
            if param not in valid_params:
                print_warning(f"Неизвестный параметр: {param}. Допустимые: {', '.join(sorted(valid_params))}")
                return True
            if param == "orchestration":
                v = value.lower().strip()
                if v not in ("parallel", "sequential", "supervisor", "hierarchical"):
                    print_error("orchestration: parallel | sequential | supervisor | hierarchical")
                    return True
                value = v
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
        summary_text = format_creator_summary_text(creator_result)
        try:
            display_model_reply(0, summary_text, None)
        except Exception:
            pass
        try:
            self.ctx["print_creator_details"](creator_result, worker_panels=False)
        except TypeError:
            self.ctx["print_creator_details"](creator_result)
        except Exception:
            pass

        messages = self.ctx["messages"]
        messages.append(HumanMessage(content=f"[Creator Mode результат]\n{summary_text}"))
        messages.append(AIMessage(content=summary_text))
        try:
            self.ctx["save_state"](messages, session_id=self.ctx["session_id"])
        except Exception:
            pass
