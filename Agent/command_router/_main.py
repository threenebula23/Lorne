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


def _normalize_slash_command_input(text: str) -> str:
    """Приводит опечатки к виду ``/команда``: префикс ``.`` вместо ``/``, лишние буквы раскладки у слэша.

    Примеры: ``.model`` → ``/model``; мусор из 1–3 символов перед ``/`` в начале
    строки. Путь вида ``foo/bar`` не трогаем (короткий префикс только из
    согласованного набора символов).
    """
    raw = (text or "").strip()
    if not raw:
        return raw
    if raw.startswith("/"):
        return raw

    m = raw.lower()
    if m.startswith(".ь/") or m.startswith("ь/"):
        return "/" + raw.split("/", 1)[1]

    if raw.startswith(".") and len(raw) > 1 and (raw[1].isalpha() or raw[1] in "/_"):
        return "/" + raw[1:]

    slash_idx = raw.find("/")
    if 0 < slash_idx <= 3:
        prefix = raw[:slash_idx]
        if all(ch in ".,;:ьъбюэ" for ch in prefix.lower()):
            return raw[slash_idx:]

    return raw


def _should_autoplan(text: str) -> bool:
    """Порог «достаточно содержательный запрос» для автозапуска Creator при включённом режиме."""
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


def _sync_router_model_ctx(ctx: Dict[str, Any]) -> None:
    """Подтянуть в ctx актуальные модель/профиль после ``set_model`` / ``init_llm``.

    Глобалы агента (``Agent.agent._impl_prepare``) уже обновлены; ``ctx`` словарь
    иначе остаётся с номером строки предыдущей итерации — отсюда «чужая» модель в
    выводе и ``/profile`` после ``/model ollama``.
    """
    try:
        from Agent.agent._impl_prepare import CONTEXT_LIMIT, MODEL_NAME, MODEL_PROFILE
        from Agent.llm_provider import get_available_models

        ctx["model_name"] = MODEL_NAME
        ctx["model_profile"] = MODEL_PROFILE
        ctx["context_limit"] = CONTEXT_LIMIT
        ctx["AVAILABLE_MODELS"] = get_available_models()
    except Exception:
        pass


from ._mixin_handlers import CommandRouterMixin

class CommandRouter(CommandRouterMixin):
    """Разбор ``/команда``; при успехе меняет ``ctx``/печать и возвращает стоп-код.

    **Важно:** TUI передаёт расширенный ``ctx`` (см. ``agent.py``) — не все поля
    нужны каждой команде.
    """

    def __init__(self, ctx: Dict[str, Any]):
        """
        *ctx* — словарь с ``messages``, ``session_id``, ``tools``, маршрутизаторами
        модели, ``run_creator_mode``, ``project_structure``, ``agent_graph`` и т.д.
        """
        self.ctx = ctx

    def handle(self, user_input: str) -> Optional[bool]:
        """Возвращает ``True``/строка ``exit`` при обработке; ``None`` если это не команда."""
        user_input = _normalize_slash_command_input(user_input)
        low = user_input.lower()
        cmd = low.split(maxsplit=1)[0] if low else ""

        if low in ("/exit", "exit", "quit", "q"):
            print_info("До встречи!")
            return "exit"

        if cmd == "/help":
            parts = user_input.split(maxsplit=1)
            tail = parts[1].strip() if len(parts) > 1 else ""
            if tail:
                print_help_topic(tail)
            else:
                print_commands()
            return True

        if low == "help":
            print_commands()
            return True

        if user_input.startswith("!"):
            return self._handle_shell(user_input)

        if cmd == "/ls":
            return self._handle_ls(user_input)

        if cmd == "/tree":
            return self._handle_tree(user_input)

        if cmd == "/plan":
            return self._handle_plan()

        if cmd == "/status":
            return self._handle_status()

        if cmd == "/profile":
            return self._handle_profile(user_input)

        if cmd == "/mode":
            return self._handle_mode(user_input)

        if cmd == "/model":
            return self._handle_model(user_input)

        if cmd in ("/balance", "/credits"):
            return self._handle_balance()

        if cmd == "/compact":
            return self._handle_compact()

        if cmd == "/versions":
            return self._handle_versions(user_input)

        if cmd == "/rollback":
            return self._handle_rollback(user_input)

        if cmd == "/agent":
            return self._handle_agent(user_input)

        if cmd in (
            "/normal", "/agentmode", "/askmode", "/deepmode", "/deep",
            "/creatormode", "/researchmode", "/brainer",
        ):
            target = {
                "/normal": "agent",
                "/agentmode": "agent",
                "/askmode": "ask",
                "/deepmode": "deep",
                "/deep": "deep",
                "/creatormode": "creator",
                "/researchmode": "research",
                "/brainer": "brainer",
            }[cmd]
            parts2 = user_input.split(maxsplit=1)
            tail = parts2[1].strip() if len(parts2) > 1 else ""
            tail_l = tail.lower() if tail else ""
            if tail_l == "settings":
                return self._handle_mode(f"/mode settings {target}")
            # /deep <запрос> — сразу режим deep и задача (без второго ввода)
            if cmd == "/deep" and tail and tail_l != "settings" and not tail_l.startswith("settings "):
                if tail_l.startswith("mode "):
                    return self._handle_mode(f"/{tail}")
                if callable(self.ctx.get("set_mode")):
                    self.ctx["set_mode"]("deep")
                else:
                    ms = self.ctx.get("mode_state")
                    if isinstance(ms, list) and ms:
                        ms[0] = "deep"
                self.ctx["pending_user_input"] = tail
                preview = (tail[:200] + "…") if len(tail) > 200 else tail
                print_success(f"Режим deep, задача: {preview}")
                return True
            return self._handle_mode(f"/mode {target}")

        if cmd == "/custom":
            return self._handle_custom(user_input)

        if cmd == "/creator":
            return self._handle_creator(user_input)

        if cmd == "/research":
            return self._handle_research(user_input)

        if cmd == "/rag":
            return self._handle_rag(user_input)

        if cmd == "/git":
            return self._handle_git(user_input)

        if cmd == "/ollama":
            return self._handle_ollama(user_input)

        if cmd == "/stop":
            return self._handle_stop()

        if cmd == "/deepcp":
            return self._handle_deep_checkpoint(user_input)

        if cmd == "/theme":
            return self._handle_theme(user_input)

        if cmd in ("/accent", "/acsent"):
            return self._handle_accent(user_input)

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
            result = plan_tool.invoke({"action": "load"})
            from Interface.visualization import display_tool_result as _dtr
            _dtr(0, "plan_tool", result)
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
        _sync_router_model_ctx(self.ctx)
        print_success(f"Переключено на: {self.ctx['model_profile']} ({self.ctx['model_name']})")
        return True

    def _handle_mode(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        mode_state = self.ctx.get("mode_state")
        set_mode = self.ctx.get("set_mode")
        current = "agent"
        if isinstance(mode_state, list) and mode_state:
            cur = str(mode_state[0] or "agent")
            if cur == "normal":
                cur = "agent"
            current = cur

        if len(parts) == 1:
            print_info_block(
                [
                    f"Текущий режим: {current}",
                    "Доступные режимы: agent, ask, deep, creator, research, brainer",
                    "(/normal — то же, что agent)",
                    "Быстрые команды: /agentmode, /askmode, /deep или /deepmode, /creatormode, /researchmode, /brainer",
                    "Старт Deep с целью: /deep <запрос>  (тот же эффект, что режим deep + ввод)",
                    "Настройки: /mode settings [agent|ask|deep|creator|research|brainer]",
                ],
                title="Режим",
                accent="accent",
            )
            return True

        target = parts[1].strip().lower()
        if target == "normal":
            target = "agent"
        if target.startswith("settings"):
            chunks = target.split()
            requested = chunks[1] if len(chunks) > 1 else current
            if requested == "normal":
                requested = "agent"
            return self._show_mode_settings(requested)
        if target not in ("agent", "ask", "deep", "creator", "research", "brainer"):
            print_warning("Использование: /mode [agent|ask|deep|creator|research|brainer]  (или /normal → agent)")
            return True

        if callable(set_mode):
            set_mode(target)
        elif isinstance(mode_state, list) and mode_state:
            mode_state[0] = target
        print_success(f"Режим: {target}")
        return True

    def _show_mode_settings(self, mode: str) -> bool:
        m = (mode or "").strip().lower()
        if m == "normal":
            m = "agent"
        if m not in ("agent", "ask", "deep", "creator", "research", "brainer"):
            print_warning("Использование: /mode settings [agent|ask|deep|creator|research|brainer]")
            return True
        print_info(f"Настройки режима: {m}")
        try:
            from Interface.ui_prefs import load_prefs
            prefs = load_prefs()
        except Exception:
            prefs = {}
        if m in ("agent", "ask"):
            print_info(f"  custom_tools_enabled: {bool(prefs.get('custom_tools_enabled', True))}")
        if m == "agent":
            print_info(f"  browser_tools_enabled: {bool(prefs.get('browser_tools_enabled', True))}")
            print_info(f"  playwright_python_enabled: {bool(prefs.get('playwright_python_enabled', False))}")
        if m == "ask":
            print_info("  Ask: только чтение, без записи в файлы и без code_interpreter.")
        if m == "brainer":
            print_info(
                "  Brainer: скан и RAG обновляются автоматически после раундов тулов и в конце хода; "
                "ручной ``project_brain_tool`` refresh — при сильных изменениях структуры репо."
            )
        if m == "deep":
            try:
                cfg = self.ctx["get_creator_config"]()
            except Exception:
                cfg = {}
            print_info(f"  local_model: {cfg.get('local_model', '—')}")
            print_info(f"  local_base_url: {cfg.get('local_base_url', '—')}")
        if m == "creator":
            try:
                cfg = self.ctx["get_creator_config"]()
            except Exception:
                cfg = {}
            print_info(f"  max_workers: {cfg.get('max_workers', '—')}")
            print_info(f"  orchestration: {cfg.get('orchestration', 'parallel')}")
            print_info(f"  local_model: {cfg.get('local_model', '—')}")
        if m == "research":
            print_info(f"  research_max_sources: {int(prefs.get('research_max_sources', 6) or 6)}")
            print_info(f"  research_max_rounds: {int(prefs.get('research_max_rounds', 3) or 3)}")
            print_info(f"  research_deep_fetch: {bool(prefs.get('research_deep_fetch', True))}")
        return True

    def _handle_model(self, user_input: str) -> bool:
        parts = user_input.split(maxsplit=1)
        models = self.ctx["AVAILABLE_MODELS"]
        set_model_fn = self.ctx["set_model"]
        init_llm = self.ctx["init_llm"]

        def _after_model_change() -> str:
            _sync_router_model_ctx(self.ctx)
            return str(self.ctx.get("model_name") or "")

        if len(parts) > 1 and parts[1].strip():
            custom_model = parts[1].strip()
            if custom_model.lower() in ("ollama", "ollama-menu", "local"):
                return self._ollama_pick_interactive()
            try:
                set_model_fn(custom_model)
            except ValueError as e:
                print_error(str(e))
                return True
            init_llm()
            mn = _after_model_change()
            print_success(f"Модель установлена: {mn}")
            print_info("Выбор сохранён и будет использоваться при следующем запуске")
            return True

        display_model_selector(models, self.ctx["model_name"])
        print_info("Как выбрать: введи номер из списка и нажми Enter (например: 3)")
        print_info("Или: /model <id>   (например: /model openai/gpt-5-mini)")
        print_info("Ollama: /model ollama — список моделей с сервера и выбор по номеру или тегу")
        print_info("        или сразу: /model ollama/llama3.2:latest")

        # С Rich-таблицей несовместимо второе меню (simple_term_menu): оно срабатывало
        # до ввода номера и оставляло странное состояние ввода. Меню — только без Rich.
        if not HAS_RICH:
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
                    try:
                        set_model_fn(chosen)
                    except ValueError as e:
                        print_error(str(e))
                        return True
                    init_llm()
                    print_success(f"Модель: {_after_model_change()}")
                    print_info("Выбор сохранён")
                return True
            except (ImportError, Exception):
                pass

        try:
            choice = read_cli_line("❯ ")
        except (EOFError, KeyboardInterrupt):
            return True
        if not choice:
            return True
        low = choice.lower()
        if low in ("/exit", "exit", "quit", "q"):
            print_info("Отмена выбора модели.")
            return True
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                chosen = models[idx]["id"]
                try:
                    set_model_fn(chosen)
                except ValueError as e:
                    print_error(str(e))
                    return True
                init_llm()
                print_success(f"Модель: {_after_model_change()}")
                print_info("Выбор сохранён")
            else:
                print_error(f"Неверный номер. Введи 1-{len(models)}")
        else:
            try:
                set_model_fn(choice)
            except ValueError as e:
                print_error(str(e))
                return True
            init_llm()
            print_success(f"Модель: {_after_model_change()}")
            print_info("Выбор сохранён")
        return True

    def _ollama_pick_interactive(self) -> bool:
        """Показать теги с Ollama и установить текущую модель агента (ollama/<тег>)."""
        try:
            from Interface.ui_prefs import load_prefs, save_prefs
            from Agent.llm_provider import fetch_ollama_models
        except Exception as e:
            print_error(f"Ollama: {e}")
            return True

        prefs = load_prefs()
        base_url = str(prefs.get("ollama_base_url") or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1")
        api_key = str(prefs.get("ollama_api_key") or os.getenv("OLLAMA_API_KEY") or "")
        rows = fetch_ollama_models(base_url=base_url, api_key=api_key)
        # Deterministic order: table row # must match digit selection (same list).
        rows = sorted(
            rows,
            key=lambda r: str((r or {}).get("name") or "").lower(),
        )
        if not rows:
            print_warning("С сервера Ollama моделей нет (пустой список). Запусти Ollama или проверь URL.")
            print_info("Пример URL: /ollama set-url http://127.0.0.1:11434/v1")
            print_info("Узнать теги вручную: /ollama list  |  выбрать без меню: /model ollama/<тег>")
            return True

        show = rows[:50]
        cur = str(self.ctx.get("model_name") or "")
        if HAS_RICH and console:
            from Interface.visualization import _cli_p
            from rich.table import Table
            from rich import box as rbox

            _tp = _cli_p()
            table = Table(
                box=rbox.ROUNDED,
                border_style=_tp["accent"],
                padding=(0, 1),
                title="[bold white]  Модели Ollama (локально) [/bold white]",
                caption=(
                    "[dim]Номер строки или полный тег; пустой ввод — отмена. "
                    f"Показано {len(show)} из {len(rows)}[/dim]"
                ),
                caption_justify="center",
            )
            table.add_column("#", style="bold", width=3, justify="right")
            table.add_column("Модель", min_width=22)
            table.add_column("Контекст", justify="right", style="dim")
            table.add_column("Тариф", justify="center", width=12)
            tier_str = "[green]🆓 локально[/green]"
            for i, m in enumerate(show, 1):
                nm = str(m.get("name") or "")
                ctx = int(m.get("ctx") or 0)
                oid = f"ollama/{nm}"
                is_current = oid == cur or nm == cur.replace("ollama/", "", 1)
                name_str = f"[bold green]{nm} ◀[/bold green]" if is_current else nm
                model_link = f"[link=https://ollama.com/library][dim]{oid}[/dim][/link]"
                table.add_row(str(i), f"{name_str}\n{model_link}", f"{ctx:,}", tier_str)
            console.print()
            console.print(table)
            console.print()
        else:
            print_info("── Модели на сервере Ollama ──")
            for i, m in enumerate(show, 1):
                nm = str(m.get("name") or "")
                ctx = int(m.get("ctx") or 0)
                print_info(f"  {i:>2}. {nm}   ctx≈{ctx:,}")
            if len(rows) > len(show):
                print_info(f"  … показано {len(show)} из {len(rows)}")
            print_info("")
        print_info("Введи номер строки или полный тег модели (как в колонке выше). Пустой ввод — отмена.")
        line = read_cli_line("❯ ")
        if not line:
            print_info("Отменено.")
            return True

        wire_name = ""
        if line.isdigit():
            idx = int(line) - 1
            if 0 <= idx < len(show):
                wire_name = str(show[idx].get("name") or "").strip()
            else:
                print_error(f"Номер от 1 до {len(show)}")
                return True
        else:
            wire_name = line.strip()
            if wire_name.lower().startswith("ollama/"):
                wire_name = wire_name.split("/", 1)[1]

        if not wire_name:
            print_error("Не удалось определить имя модели")
            return True

        model_id = f"ollama/{wire_name}"
        set_model_fn = self.ctx["set_model"]
        init_llm = self.ctx["init_llm"]
        try:
            set_model_fn(model_id)
        except ValueError as e:
            print_error(str(e))
            return True
        init_llm()

        ctx_val = 32768
        for m in rows:
            if str(m.get("name") or "").strip() == wire_name:
                ctx_val = int(m.get("ctx") or 32768)
                break
        cur = [m for m in (prefs.get("ollama_custom_models") or []) if isinstance(m, dict)]
        cur = [m for m in cur if str(m.get("name") or "") != wire_name]
        cur.append({"name": wire_name, "label": f"Ollama · {wire_name}", "ctx": ctx_val})
        save_prefs(ollama_custom_models=cur)

        _sync_router_model_ctx(self.ctx)
        print_success(f"Текущая модель: {self.ctx['model_name']}")
        print_info("Добавлено в список моделей; дальше можно переключаться номером в /model")
        return True

    def _handle_balance(self) -> bool:
        print_info("Запрос баланса OpenRouter…")
        creds = self.ctx["fetch_openrouter_credits"]()
        if creds is None:
            print_error("Не удалось получить данные. Проверь OPENROUTER_API_KEY.")
        else:
            try:
                u = float(creds.get("usage") or 0)
                from Interface.panels.usage_calendar import record_cumulative_usage

                record_cumulative_usage(u)
            except Exception:
                pass
            info = self.ctx["format_credits_info"](creds)
            if HAS_RICH and console:
                from Interface.visualization import _cli_p
                from Interface.panels.usage_calendar import render_cli_usage_calendar_text
                from rich.console import Group
                from rich.panel import Panel as RPanel
                from rich.rule import Rule
                from rich.text import Text
                from rich import box as rbox

                pal = _cli_p()
                cal = render_cli_usage_calendar_text()
                inner = Group(Text(info), Rule(style=pal["accent"]), cal)
                console.print(
                    RPanel(
                        inner,
                        title="[bold]OpenRouter — Счёт[/bold]",
                        border_style=pal["accent"],
                        box=rbox.ROUNDED,
                        padding=(1, 2),
                    )
                )
            else:
                print_info("═ OpenRouter — Счёт ═")
                for line in info.split("\n"):
                    print_info(f"  {line}")
        return True

    def _handle_compact(self) -> bool:
        try:
            from Agent.message_utils import compact_conversation
        except ImportError:
            from message_utils import compact_conversation
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

