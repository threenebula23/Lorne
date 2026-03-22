"""
Красивый терминальный вывод для TCA агента — вдохновлён Claude Code.
Использует `rich` для панелей, подсветки синтаксиса, спиннеров, Markdown, прогресс-баров.
Если rich не установлен, используется plain ANSI.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.markdown import Markdown as RichMarkdown
    from rich.table import Table
    from rich.text import Text
    from rich.columns import Columns
    from rich.rule import Rule
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn
    from rich.theme import Theme
    from rich import box

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

_theme = Theme({
    "info": "#A78BFA",
    "success": "bold #10B981",
    "warning": "bold #F59E0B",
    "error": "bold #EF4444",
    "tool": "bold #8B5CF6",
    "dim": "#6B7280",
    "accent": "bold #8B5CF6",
    "header": "bold #E5E7EB on #1a1a2e",
}) if HAS_RICH else None

console = Console(theme=_theme, highlight=False) if HAS_RICH else None

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[38;2;167;139;250m"   # #A78BFA purple-light
GREEN = "\033[38;2;16;185;129m"   # #10B981
YELLOW = "\033[38;2;245;158;11m"  # #F59E0B
MAGENTA = "\033[38;2;139;92;246m" # #8B5CF6
BLUE = "\033[38;2;139;92;246m"    # #8B5CF6 (purple as primary)
RED = "\033[38;2;239;68;68m"      # #EF4444
WHITE = "\033[38;2;229;231;235m"  # #E5E7EB

# ─── Лимиты контекста по моделям ──────────────────────────────────
# Built dynamically from AVAILABLE_MODELS in llm_provider to avoid
# maintaining two separate lists. Falls back to a static dict for models
# that are not in the curated list (e.g. custom OpenRouter model IDs).
DEFAULT_CONTEXT_LIMIT = 128_000

_MODEL_CTX_CACHE: Optional[Dict[str, int]] = None


def _build_ctx_cache() -> Dict[str, int]:
    global _MODEL_CTX_CACHE
    if _MODEL_CTX_CACHE is not None:
        return _MODEL_CTX_CACHE
    result: Dict[str, int] = {}
    try:
        from Agent.llm_provider import AVAILABLE_MODELS as _models
    except ImportError:
        _models = []
    for m in _models:
        result[m["id"]] = m["ctx"]
    _MODEL_CTX_CACHE = result
    return result


def get_context_limit(model_name: str) -> int:
    ctx_map = _build_ctx_cache()
    if model_name in ctx_map:
        return ctx_map[model_name]
    for key, limit in ctx_map.items():
        if key in (model_name or "") or (model_name or "") in key:
            return limit
    return DEFAULT_CONTEXT_LIMIT


def _short_path(p: str, max_len: int = 60) -> str:
    try:
        s = str(Path(p).resolve())
        if len(s) <= max_len:
            return s
        return "…" + s[-(max_len - 1):]
    except Exception:
        return str(p)[:max_len]


def _detect_language(filename: str) -> str:
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "tsx", ".jsx": "jsx", ".html": "html", ".css": "css",
        ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml",
        ".md": "markdown", ".rs": "rust", ".go": "go", ".java": "java",
        ".c": "c", ".cpp": "cpp", ".h": "c", ".rb": "ruby", ".php": "php",
        ".sh": "bash", ".sql": "sql", ".kt": "kotlin", ".cs": "csharp",
    }
    suffix = Path(filename).suffix.lower()
    return ext_map.get(suffix, "text")


def _truncate(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


# ═══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════

def section(title: str, char: str = "═") -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_separator(title)
        return
    if HAS_RICH:
        console.print()
        console.print(Rule(f"[bold]{title}[/bold]", style="blue"))
        console.print()
    else:
        line = char * min(60, len(title) + 6)
        print(f"\n{DIM}{line}{RESET}")
        print(f"{BOLD}{title}{RESET}")
        print(f"{DIM}{line}{RESET}")


def step(num: int, title: str, detail: str = "") -> None:
    if HAS_RICH:
        marker = f"[cyan]●[/cyan] [bold]Шаг {num}[/bold]: {title}"
        if detail:
            marker += f"  [dim]{detail}[/dim]"
        console.print(marker)
    else:
        print(f"\n{CYAN}● Шаг {num}: {title}{RESET}")
        if detail:
            print(f"   {DIM}{detail}{RESET}")


def round_header(round_num: int) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_separator(f"Round {round_num}")
        return
    if HAS_RICH:
        console.print()
        console.print(
            Panel(
                f"[bold white]Раунд {round_num}[/bold white]",
                style="blue",
                box=box.DOUBLE,
                expand=False,
                padding=(0, 3),
            )
        )
    else:
        print(f"\n{BOLD}{BLUE}{'═' * 52}{RESET}")
        print(f"{BOLD}{BLUE}  Раунд {round_num}{RESET}")
        print(f"{BOLD}{BLUE}{'═' * 52}{RESET}")


def display_agent_action(step_num: int, name: str, args: Dict[str, Any]) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        return

    short_args = {}
    for k, v in args.items():
        if k in ("new_str", "code", "snippet", "content") and isinstance(v, str):
            lines = v.count("\n") + 1
            short_args[k] = f"<{len(v)} симв., {lines} строк>"
        elif k == "old_str" and isinstance(v, str) and len(v) > 80:
            short_args[k] = v[:80] + "…"
        else:
            short_args[k] = v

    if HAS_RICH:
        args_str = json.dumps(short_args, ensure_ascii=False, indent=2)
        tool_text = Text()
        tool_text.append("⚡ ", style="yellow")
        tool_text.append(name, style="bold magenta")

        panel_content = Text(args_str, style="dim")
        console.print(
            Panel(
                panel_content,
                title=tool_text,
                title_align="left",
                border_style="magenta",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        step(step_num, f"Инструмент: {name}", "")
        args_json = json.dumps(short_args, ensure_ascii=False)
        print(f"   {DIM}{args_json}{RESET}")


def display_tool_result(step_num: int, name: str, result: Any) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_tool_result(name, result)
        return

    if name in ("save_plan", "update_plan", "load_plan", "clear_plan"):
        _display_plan_result(name, result)
        return

    if name == "read_file" and isinstance(result, dict):
        _display_read_file_result(result)
        return

    if name == "run_command" and isinstance(result, dict):
        _display_command_result(result)
        return

    if name in ("edit_file", "write_file", "create_code_file", "append_code_snippet"):
        _display_file_change_result(name, result)
        return

    if name == "list_files" and isinstance(result, dict):
        _display_list_files_result(result)
        return

    if name == "search_in_files" and isinstance(result, dict):
        _display_search_result(result)
        return

    if HAS_RICH:
        s = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, dict) else str(result)
        console.print(
            Panel(
                _truncate(s, 500),
                title=f"[dim]Результат: {name}[/dim]",
                title_align="left",
                border_style="dim",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        step(step_num, f"Результат: {name}", "")
        s = str(result)
        print(f"   {DIM}{_truncate(s, 400)}{RESET}")


def _display_plan_result(name: str, result: Any) -> None:
    if not isinstance(result, dict):
        return
    if HAS_RICH:
        if name == "save_plan":
            console.print(f"  [success]✓ План сохранён[/success] ({result.get('step_count', '?')} шагов)")
        elif name == "update_plan":
            if result.get("ok"):
                status = result.get("status", "")
                icon = {"completed": "✓", "in_progress": "▶", "blocked": "⚠", "pending": "○"}.get(status, "●")
                console.print(f"  [info]{icon} Шаг {result.get('step_index')} → {status}[/info]")
            else:
                console.print(f"  [warning]Ошибка плана: {result.get('error')}[/warning]")
        elif name == "load_plan":
            plan = result.get("plan") or {}
            if not result.get("ok"):
                console.print("  [dim]Нет активного плана[/dim]")
                return
            table = Table(title=plan.get("title", "План"), box=box.SIMPLE, show_header=False, padding=(0, 1))
            table.add_column("Статус", width=3)
            table.add_column("Шаг")
            for s in (plan.get("steps") or [])[:15]:
                status = s.get("status", "pending")
                icon = {"completed": "[green]✓[/green]", "in_progress": "[yellow]▶[/yellow]", "blocked": "[red]⚠[/red]"}.get(status, "[dim]○[/dim]")
                table.add_row(icon, s.get("text", ""))
            console.print(table)
        elif name == "clear_plan":
            if result.get("ok"):
                console.print("  [success]✓ План очищен[/success]")
            else:
                console.print(f"  [warning]План не удалён: {result.get('error', '')}[/warning]")
    else:
        if name == "save_plan":
            print(f"   {GREEN}✓ План сохранён ({result.get('step_count')} шагов){RESET}")
        elif name == "update_plan" and result.get("ok"):
            print(f"   Шаг {result.get('step_index')} → {result.get('status')}")
        elif name == "load_plan":
            plan = result.get("plan") or {}
            for s in (plan.get("steps") or [])[:15]:
                print(f"   [{s.get('status')}] {s.get('text')}")


def _display_read_file_result(result: Dict[str, Any]) -> None:
    path = result.get("file_path", "") or result.get("path", "")
    total = result.get("total_lines", 0)
    content = result.get("content", "")

    if HAS_RICH:
        short = _short_path(path)
        lang = _detect_language(path)
        preview = content[:2000] if len(content) > 2000 else content
        if preview != content:
            preview += "\n… (обрезано)"
        console.print(
            Panel(
                Syntax(preview, lang, theme="monokai", line_numbers=True, word_wrap=True),
                title=f"[bold]{short}[/bold] [dim]({total} строк)[/dim]",
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(0, 0),
            )
        )
    else:
        print(f"   {DIM}Прочитано: {_short_path(path)}  ({total} строк){RESET}")


def _display_command_result(result: Dict[str, Any]) -> None:
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    rc = result.get("returncode", -1)
    skipped = result.get("skipped", False)

    if HAS_RICH:
        if skipped:
            console.print(f"  [warning]⏭ Команда пропущена: {stderr.strip()}[/warning]")
            return
        style = "green" if rc == 0 else "red"
        icon = "✓" if rc == 0 else "✗"
        header = f"[{style}]{icon} Код выхода: {rc}[/{style}]"

        output_parts = []
        if stdout.strip():
            output_parts.append(stdout.strip()[:3000])
        if stderr.strip():
            output_parts.append(f"[red]{stderr.strip()[:1000]}[/red]")
        body = "\n".join(output_parts) if output_parts else "[dim]Нет вывода[/dim]"

        console.print(
            Panel(
                body,
                title=f"[bold]Терминал[/bold]  {header}",
                title_align="left",
                border_style=style,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        icon = "✓" if rc == 0 else "✗"
        print(f"   {icon} Код выхода: {rc}")
        if stdout.strip():
            for line in stdout.strip().splitlines()[:30]:
                print(f"   {line}")
        if stderr.strip():
            print(f"   {RED}{stderr.strip()[:500]}{RESET}")


def _display_file_change_result(name: str, result: Any) -> None:
    if not isinstance(result, dict):
        return
    path = result.get("path", "")
    action = result.get("action", "")
    short = _short_path(path)
    after_total = result.get("after_total_lines") or result.get("total_lines") or 0
    before_total = result.get("before_total_lines", 0)
    delta = result.get("delta_total_lines", after_total - before_total)
    sign = "+" if delta >= 0 else ""
    snap = (result.get("snapshot_id") or "").strip()

    action_labels = {
        "created_file": ("Создан", "green"),
        "written": ("Записан", "green"),
        "code_written": ("Создан", "green"),
        "snippet_appended": ("Дополнен", "green"),
        "edited": ("Изменён", "yellow"),
        "old_str not found": ("Не найдено", "red"),
        "file_not_found": ("Файл не найден", "red"),
    }
    label, color = action_labels.get(action, (action, "white"))

    if HAS_RICH:
        delta_str = f"[dim]({sign}{delta})[/dim]" if delta != 0 else ""
        snap_str = f"  [dim]snapshot:{snap}[/dim]" if snap else ""
        console.print(
            f"  [{color}]{'✓' if color == 'green' else '●'} {label}[/{color}]  "
            f"[bold]{short}[/bold]  [dim]{after_total} строк[/dim] {delta_str}{snap_str}"
        )
        if action == "edited":
            before_frag = result.get("lines_before", 0)
            after_frag = result.get("lines_after", 0)
            d = result.get("lines_delta", 0)
            s2 = "+" if d >= 0 else ""
            console.print(f"    [dim]фрагмент: {before_frag} → {after_frag} строк ({s2}{d})[/dim]")
    else:
        print(f"   {GREEN if color == 'green' else YELLOW}{label}:{RESET} {short}  {after_total} строк ({sign}{delta})")


def _display_list_files_result(result: Dict[str, Any]) -> None:
    entries = result.get("entries", [])
    path = result.get("path", "")
    if HAS_RICH:
        if len(entries) == 0:
            console.print(f"  [dim]Пустая директория: {_short_path(path)}[/dim]")
            return
        items = []
        for e in entries[:40]:
            n = e.get("name", "") if isinstance(e, dict) else str(e)
            t = e.get("type", "") if isinstance(e, dict) else ""
            icon = "📁" if t == "dir" else "📄"
            items.append(f"{icon} {n}")
        cols = Columns(items, padding=(0, 3), equal=False)
        console.print(
            Panel(
                cols,
                title=f"[bold]{_short_path(path)}[/bold] [dim]({len(entries)} элементов)[/dim]",
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        if len(entries) > 40:
            console.print(f"  [dim]… и ещё {len(entries) - 40}[/dim]")
    else:
        print(f"   {_short_path(path)}  ({len(entries)} элементов)")
        for e in entries[:30]:
            n = e.get("name", "") if isinstance(e, dict) else str(e)
            print(f"     {n}")


def _display_search_result(result: Dict[str, Any]) -> None:
    matches = result.get("matches", [])
    query = result.get("query", "")
    if HAS_RICH:
        if not matches:
            console.print(f"  [dim]Нет совпадений для '{query}'[/dim]")
            return
        table = Table(title=f"Поиск: '{query}'", box=box.SIMPLE, padding=(0, 1))
        table.add_column("Файл", style="cyan")
        table.add_column("Строки", style="dim")
        for m in matches[:20]:
            f = _short_path(m.get("file", ""), 50)
            lines = ", ".join(str(l) for l in (m.get("lines") or [])[:10])
            table.add_row(f, lines)
        console.print(table)
    else:
        print(f"   Поиск: '{query}' — {len(matches)} совпадений")
        for m in matches[:15]:
            print(f"     {m.get('file', '')}: строки {m.get('lines', [])[:5]}")


def display_model_reply(step_num: int, content: str, response_metadata: Optional[Dict[str, Any]] = None) -> None:
    if not content or not content.strip():
        return

    bridge = _get_tui_bridge()
    if bridge:
        return
        
    import re as _re
    clean_content = _re.sub(r"<thought>[\s\S]*?</thought>", "", content).strip()
    if not clean_content:
        return

    if HAS_RICH:
        try:
            md = RichMarkdown(clean_content)
            console.print(
                Panel(
                    md,
                    title="[bold white]Ассистент[/bold white]",
                    title_align="left",
                    border_style="green",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
        except Exception:
            console.print(
                Panel(
                    content.strip()[:3000],
                    title="[bold white]Ассистент[/bold white]",
                    title_align="left",
                    border_style="green",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
    else:
        step(step_num, "Ответ ассистента", "")
        print(content.strip()[:2000])
        print()


def display_turn_summary(file_changes: List[Dict[str, Any]]) -> None:
    if not file_changes:
        return
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info(f"Files changed: {len(file_changes)}")
        for fc in file_changes:
            path_short = _short_path(fc.get("path", ""), 50)
            action = fc.get("action", "")
            bridge.on_info(f"  {action}: {path_short}")
        return

    if HAS_RICH:
        console.print()
        table = Table(
            title="[bold]Файлы изменённые за ход[/bold]",
            box=box.SIMPLE_HEAVY,
            padding=(0, 1),
            show_lines=False,
        )
        table.add_column("Действие", style="green", width=12)
        table.add_column("Файл", style="bold")
        table.add_column("Строк", justify="right", style="dim")
        table.add_column("Δ", justify="right")

        for fc in file_changes:
            path_short = _short_path(fc.get("path", ""), 50)
            action = fc.get("action", "")
            after_total = fc.get("after_total_lines") or fc.get("total_lines") or 0
            before_total = fc.get("before_total_lines", 0)
            delta = fc.get("delta_total_lines", after_total - before_total)
            sign = "+" if delta >= 0 else ""
            delta_style = "green" if delta > 0 else ("red" if delta < 0 else "dim")

            action_labels = {
                "created_file": "Создан",
                "written": "Записан",
                "code_written": "Создан",
                "snippet_appended": "Дополнен",
                "edited": "Изменён",
            }
            label = action_labels.get(action, action)
            table.add_row(label, path_short, str(after_total), f"[{delta_style}]{sign}{delta}[/{delta_style}]")

        console.print(table)
        console.print()
    else:
        print(f"\n{DIM}{'─' * 50}{RESET}")
        print(f"{BOLD}Файлы за ход:{RESET}")
        for fc in file_changes:
            path_short = _short_path(fc.get("path", ""), 50)
            after_total = fc.get("after_total_lines") or fc.get("total_lines") or 0
            before_total = fc.get("before_total_lines", 0)
            delta = fc.get("delta_total_lines", after_total - before_total)
            sign = "+" if delta >= 0 else ""
            print(f"  {GREEN}●{RESET} {path_short}  {after_total} строк ({sign}{delta})")
        print()


def display_usage(
    meta: Dict[str, Any],
    context_limit: Optional[int] = None,
    prefix: str = "   ",
) -> Dict[str, int]:
    usage = meta.get("usage") or meta.get("token_usage") or {}
    inp = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    out = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    total = usage.get("total_tokens")
    if total is None and (inp or out):
        total = inp + out
    if not (inp or out or total):
        return {}

    bridge = _get_tui_bridge()
    if bridge:
        return {"input_tokens": inp, "output_tokens": out, "total_tokens": total or inp + out}

    if HAS_RICH:
        pct = round(100 * (total or 0) / context_limit, 1) if context_limit and context_limit > 0 else 0
        bar_len = 20
        filled = int(bar_len * pct / 100) if pct <= 100 else bar_len
        bar_color = "green" if pct < 50 else ("yellow" if pct < 80 else "red")
        bar = f"[{bar_color}]{'█' * filled}{'░' * (bar_len - filled)}[/{bar_color}]"
        console.print(
            f"{prefix}[dim]Токены: вход={inp:,}  выход={out:,}  всего={total:,}[/dim]  "
            f"{bar} [dim]{pct}%[/dim]"
        )
    else:
        parts = []
        if inp:
            parts.append(f"вход: {inp}")
        if out:
            parts.append(f"выход: {out}")
        if total:
            parts.append(f"всего: {total}")
        line = f"{MAGENTA}{prefix}Токены: {', '.join(parts)}{RESET}"
        if context_limit and context_limit > 0:
            pct = round(100 * (total or 0) / context_limit, 1)
            line += f"  {DIM}(лимит: {context_limit:,} | использовано: {pct}%){RESET}"
        print(line)

    return {"input_tokens": inp, "output_tokens": out, "total_tokens": total or inp + out}


def display_cumulative_usage(
    cumulative: Dict[str, int],
    context_limit: int,
    model_name: str = "",
) -> None:
    if not cumulative:
        return
    bridge = _get_tui_bridge()
    if bridge:
        total = cumulative.get("total_tokens", 0)
        bridge.on_context_update(total, context_limit)
        return

    inp = cumulative.get("input_tokens", 0)
    out = cumulative.get("output_tokens", 0)
    total = cumulative.get("total_tokens", 0)
    pct = round(100 * total / context_limit, 1) if context_limit else 0

    if HAS_RICH:
        bar_len = 30
        filled = int(bar_len * pct / 100) if pct <= 100 else bar_len
        bar_color = "green" if pct < 50 else ("yellow" if pct < 80 else "red")
        bar = f"[{bar_color}]{'█' * filled}{'░' * (bar_len - filled)}[/{bar_color}]"

        model_str = f"  [dim]модель: {model_name}[/dim]" if model_name else ""
        console.print()
        console.print(Rule("[bold]Итог хода[/bold]", style="dim"))
        console.print(
            f"  [dim]Токены за ход:[/dim] вход=[bold]{inp:,}[/bold]  "
            f"выход=[bold]{out:,}[/bold]  всего=[bold]{total:,}[/bold]{model_str}"
        )
        console.print(f"  Контекст: {bar} [dim]{pct}% из {context_limit:,}[/dim]")
        console.print()
    else:
        print(f"{MAGENTA}   Токены за ход: вход {inp:,} | выход {out:,} | всего {total:,}{RESET}")
        print(f"{MAGENTA}   Лимит: {context_limit:,} | использовано: {pct}%{RESET}\n")


# ─── Хелперы для основного цикла агента ────────────────────────────

def print_welcome(model_name: str, profile: str, project_name: str, balance: str = "") -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info(f"TCA — {model_name} ({profile}) | Project: {project_name}")
        if balance:
            bridge.on_info(f"Balance: {balance}")
        return
    balance_line = f"\n  [dim]Баланс:[/dim]  [bold green]{balance}[/bold green]" if balance else ""
    balance_plain = f"\n  Баланс:  {balance}" if balance else ""
    if HAS_RICH:
        console.print()
        console.print(
            Panel(
                f"[bold white]TCA — Терминальный Ассистент Кодинга[/bold white]\n\n"
                f"  [dim]Модель:[/dim]   [bold]{model_name}[/bold]\n"
                f"  [dim]Профиль:[/dim] [bold]{profile}[/bold]\n"
                f"  [dim]Проект:[/dim]  [bold]{project_name}[/bold]"
                f"{balance_line}",
                border_style="#8B5CF6",
                box=box.DOUBLE,
                padding=(1, 3),
            )
        )
        console.print()
    else:
        print(f"\n{'═' * 50}")
        print(f"  TCA — Терминальный Ассистент Кодинга")
        print(f"  Модель:   {model_name}")
        print(f"  Профиль:  {profile}")
        print(f"  Проект:   {project_name}")
        if balance:
            print(f"  Баланс:  {balance}")
        print(f"{'═' * 50}\n")


def display_shell_command(command: str) -> None:
    """Display a user-initiated shell command with terminal-like styling."""
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_action("shell", command)
        return
    if HAS_RICH:
        console.print(
            Panel(
                Text.assemble(
                    ("❯ ", "bold bright_green"),
                    (command, "bold white"),
                ),
                title="[bold bright_green]  Terminal [/bold bright_green]",
                title_align="left",
                border_style="bright_green",
                box=box.HEAVY,
                padding=(0, 1),
            )
        )
    else:
        print(f"\n  {GREEN}{BOLD}$ {command}{RESET}")


def display_model_selector(models: list, current_model: str) -> None:
    """Display a rich model selection interface grouped by tier."""
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info("── Выбор модели ──")
        for i, m in enumerate(models, 1):
            cur = " ◀ текущая" if m["id"] == current_model else ""
            bridge.on_info(f"  {i:>2}. {m['name']:<25} [{m['tier']}]{cur}")
        bridge.on_info("Используй /model <id> для выбора")
        return

    if not HAS_RICH:
        for i, m in enumerate(models, 1):
            cur = " ◀ текущая" if m["id"] == current_model else ""
            print(f"  {i:>2}. {m['name']:<25} {m['id']:<45} {m['tier']}{cur}")
        return

    tier_config = {
        "free":  ("🆓", "Бесплатные", "green"),
        "cheap": ("💰", "Доступные",  "yellow"),
        "paid":  ("💎", "Премиум",    "magenta"),
        "pro":   ("👑", "Про",        "cyan"),
    }

    table = Table(
        box=box.ROUNDED,
        border_style="#8B5CF6",
        padding=(0, 1),
        title="[bold white]  Выбор модели [/bold white]",
        caption="[dim]Введи номер модели, или [bold]/model <id>[/bold] для произвольной[/dim]",
        caption_justify="center",
    )
    table.add_column("#", style="bold", width=3, justify="right")
    table.add_column("Модель", min_width=22)
    table.add_column("Контекст", justify="right", style="dim")
    table.add_column("Тариф", justify="center", width=14)

    prev_tier = None
    for i, m in enumerate(models, 1):
        tier = m["tier"]
        icon, label, color = tier_config.get(tier, ("", tier, "white"))

        if tier != prev_tier and prev_tier is not None:
            table.add_section()
        prev_tier = tier

        is_current = m["id"] == current_model
        name_str = f"[bold green]{m['name']} ◀[/bold green]" if is_current else m["name"]
        model_link = f"[link=https://openrouter.ai/models/{m['id']}][dim]{m['id']}[/dim][/link]"
        ctx_str = f"{m['ctx']:,}"
        tier_str = f"[{color}]{icon} {label}[/{color}]"

        table.add_row(str(i), f"{name_str}\n{model_link}", ctx_str, tier_str)

    console.print()
    console.print(table)
    console.print()


def display_status_panel(
    model_name: str, profile: str, context_limit: int,
    human_count: int, ai_count: int, tool_count: int, total: int,
) -> None:
    """Display a formatted status panel for /status command."""
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info(f"Модель: {model_name} ({profile})")
        bridge.on_info(f"Контекст: {context_limit:,} токенов")
        bridge.on_info(f"Сообщения: 👤 {human_count}  🤖 {ai_count}  🔧 {tool_count}  Σ {total}")
        return

    if not HAS_RICH:
        print(f"  Профиль: {profile} | Модель: {model_name}")
        print(f"  Лимит контекста: {context_limit:,} токенов")
        print(f"  Сообщения: {human_count} user, {ai_count} ai, {tool_count} tools = {total}")
        return

    pct = 0
    if context_limit > 0:
        approx_tokens = total * 150
        pct = round(100 * approx_tokens / context_limit, 1)
    bar_len = 20
    filled = min(int(bar_len * pct / 100), bar_len)
    bar_color = "green" if pct < 50 else ("yellow" if pct < 80 else "red")
    bar = f"[{bar_color}]{'█' * filled}{'░' * (bar_len - filled)}[/{bar_color}] [dim]{pct}%[/dim]"

    model_link = f"[link=https://openrouter.ai/models/{model_name}]{model_name}[/link]"

    content = (
        f"  [dim]Модель:[/dim]    [bold cyan]{model_link}[/bold cyan]\n"
        f"  [dim]Профиль:[/dim]  [bold]{profile}[/bold]\n"
        f"  [dim]Контекст:[/dim] [bold]{context_limit:,}[/bold] токенов\n\n"
        f"  [dim]Сообщения:[/dim]\n"
        f"    [cyan]👤[/cyan] Пользователь  [bold]{human_count}[/bold]\n"
        f"    [green]🤖[/green] Ассистент      [bold]{ai_count}[/bold]\n"
        f"    [magenta]🔧[/magenta] Инструменты    [bold]{tool_count}[/bold]\n"
        f"    [dim]━━━━━━━━━━━━━━━━━━━━[/dim]\n"
        f"    [bold]Σ  Всего           {total}[/bold]\n\n"
        f"  [dim]Заполнение контекста:[/dim] {bar}"
    )
    console.print(
        Panel(
            content,
            title="[bold]  Статус сессии [/bold]",
            border_style="#8B5CF6",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


_HELP_CATEGORIES = [
    ("💬 Чат", [
        ("Enter", "Продолжить (следующий шаг)"),
        ("!<команда>", "Выполнить команду в терминале"),
    ]),
    ("🤖 Модель", [
        ("/model", "Выбрать модель (сохраняется)"),
        ("/profile [имя]", "fast / balanced / quality"),
        ("/balance", "Баланс OpenRouter"),
    ]),
    ("📁 Проект", [
        ("/ls [путь]", "Список файлов"),
        ("/tree [путь]", "Дерево проекта"),
        ("/rag <запрос>", "Поиск по проекту (RAG)"),
        ("/plan", "Текущий план задачи"),
        ("/status", "Статус сессии"),
    ]),
    ("🔄 История", [
        ("/versions <файл>", "Версии файла (SQLite)"),
        ("/rollback <файл>", "Откатить файл (SQLite)"),
        ("/git log [файл]", "История Git-коммитов"),
        ("/git diff [хеш]", "Показать Git-diff"),
        ("/git rollback <хеш>", "Откатить Git-коммит"),
        ("/git status", "Статус Git"),
        ("/compact", "Сжать контекст"),
    ]),
    ("🔧 Custom Tools", [
        ("/custom", "Список кастомных тулов"),
        ("/custom add <имя>", "Добавить свой тул"),
        ("/custom remove <имя>", "Удалить тул"),
        ("/custom reload", "Перезагрузить тулы"),
    ]),
    ("⚡ Creator Mode", [
        ("/creator", "Включить creator mode"),
        ("/creator <задача>", "Запустить задачу в creator mode"),
        ("/creator config", "Конфигурация creator"),
        ("/creator set <key> <val>", "Изменить настройку"),
        ("/creator off", "Выключить creator mode"),
    ]),
    ("⚙️  Система", [
        ("/agent list|use", "Управление под-агентами"),
        ("/help", "Эта справка"),
        ("/exit", "Выход"),
    ]),
]


def print_commands() -> None:
    bridge = _get_tui_bridge()
    if bridge:
        for cat_name, cmds in _HELP_CATEGORIES:
            bridge.on_info(f"── {cat_name} ──")
            for cmd, desc in cmds:
                bridge.on_info(f"  {cmd:<24} {desc}")
        return

    if HAS_RICH:
        table = Table(
            box=box.SIMPLE,
            padding=(0, 2),
            show_header=False,
            show_edge=False,
        )
        table.add_column("Команда", min_width=24)
        table.add_column("Описание", style="dim")

        for cat_name, cmds in _HELP_CATEGORIES:
            table.add_row(f"\n[bold]{cat_name}[/bold]", "")
            for cmd, desc in cmds:
                table.add_row(f"  [cyan bold]{cmd}[/cyan bold]", desc)

        console.print(
            Panel(
                table,
                title="[bold]  Справка [/bold]",
                border_style="#8B5CF6",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        all_cmds = []
        for _, cmds in _HELP_CATEGORIES:
            all_cmds.extend(cmds)
        for cmd, desc in all_cmds:
            clean = cmd.replace("[bright_green]", "").replace("[/bright_green]", "")
            print(f"  {CYAN}{clean:<22}{RESET} {desc}")
    print()


def print_session_list(sessions: list) -> None:
    if not sessions:
        return
    bridge = _get_tui_bridge()
    if bridge:
        return
    if HAS_RICH:
        table = Table(title="[bold]Доступные сессии[/bold]", box=box.SIMPLE, padding=(0, 1))
        table.add_column("#", style="bold", width=3)
        table.add_column("Название", style="cyan")
        table.add_column("Сообщений", justify="right", style="dim")
        table.add_column("Обновлено", style="dim")
        for i, s in enumerate(sessions, start=1):
            table.add_row(
                str(i),
                s.get("title", "без имени"),
                str(s.get("message_count", 0)),
                s.get("updated_at", ""),
            )
        console.print(table)
    else:
        print(f"{CYAN}Доступные сессии:{RESET}")
        for i, s in enumerate(sessions, start=1):
            print(f"  {i}) {s.get('title', '')}  (сообщ.={s.get('message_count', 0)}, обновлено={s.get('updated_at', '')})")


def print_thinking(thought: str = "") -> None:
    bridge = _get_tui_bridge()
    if bridge:
        if thought:
            bridge.on_thought(thought)
        return

    if not thought:
        if HAS_RICH:
            console.print("[dim]  ⏳ Думаю…[/dim]")
        else:
            print("  ⏳ Думаю…")
        return

    if HAS_RICH:
        console.print(
            Panel(
                Text(thought, style="italic cyan"),
                title="[bold cyan]🤔 Рассуждение[/bold cyan]",
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        print(f"\n{CYAN}🤔 Рассуждение:{RESET}")
        print(f"   {thought}")


def print_planning(task: str) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info(f"📋 Planning: {_truncate(task, 100)}")
        return
    if HAS_RICH:
        console.print(f"\n[dim]  📋 Составляю план:[/dim] [bold]{_truncate(task, 100)}[/bold]")
    else:
        print(f"\n   📋 Составляю план: {_truncate(task, 100)}")


def _get_tui_bridge():
    """Return the active TUI bridge, if any."""
    try:
        from Interface.tui_bridge import get_bridge
        return get_bridge()
    except Exception:
        return None


def print_info(message: str) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info(message)
        return
    if HAS_RICH:
        console.print(f"  [info]{message}[/info]")
    else:
        print(f"  {CYAN}{message}{RESET}")


def print_success(message: str) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_success(message)
        return
    if HAS_RICH:
        console.print(f"  [success]✓ {message}[/success]")
    else:
        print(f"  {GREEN}✓ {message}{RESET}")


def print_warning(message: str) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_warning(message)
        return
    if HAS_RICH:
        console.print(f"  [warning]⚠ {message}[/warning]")
    else:
        print(f"  {YELLOW}⚠ {message}{RESET}")


def print_error(message: str) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_error(message)
        return
    if HAS_RICH:
        console.print(f"  [error]✗ {message}[/error]")
    else:
        print(f"  {RED}✗ {message}{RESET}")


def get_user_input() -> str:
    if HAS_RICH:
        try:
            return console.input("[bold blue]❯[/bold blue] ")
        except (KeyboardInterrupt, EOFError):
            return "/exit"
    else:
        try:
            return input(f"{BLUE}❯{RESET} ")
        except (KeyboardInterrupt, EOFError):
            return "/exit"


def display_file_diffs(files: List[str]) -> None:
    """Визуализация списка измененных файлов (как в обычном агенте)."""
    if not files:
        return

    if HAS_RICH:
        table = Table(
            title="[bold green]Измененные файлы[/bold green]",
            box=box.SIMPLE_HEAVY,
            padding=(0, 1),
        )
        table.add_column("Файл", style="bold white")
        table.add_column("Статус", style="green")

        for f in sorted(files):
            table.add_row(f, "✓ Готово")

        console.print(table)
    else:
        print(f"\n{GREEN}Измененные файлы:{RESET}")
        for f in sorted(files):
            print(f"  ✓ {f}")


# ─── RAG progress display ──────────────────────────────────────────

def display_rag_progress(current: int, total: int) -> None:
    """Display RAG indexing progress inline."""
    if total <= 0:
        return
    bridge = _get_tui_bridge()
    if bridge:
        if current >= total:
            bridge.on_info(f"RAG indexed: {total} files")
        return
    pct = int(100 * current / total)
    bar_len = 30
    filled = int(bar_len * current / total)
    bar = "█" * filled + "░" * (bar_len - filled)
    line = f"\r  Индексация: {bar} {pct}% ({current}/{total} файлов)  "
    import sys
    sys.stdout.write(line)
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


def display_rag_results(results: List[Dict[str, Any]], query_text: str) -> None:
    """Display RAG search results in a formatted table."""
    bridge = _get_tui_bridge()
    if bridge:
        if not results:
            bridge.on_info(f"RAG: нет результатов для '{query_text}'")
            return
        bridge.on_info(f"RAG: '{query_text}' — {len(results)} результатов")
        for r in results:
            path = _short_path(r.get("path", ""), 50)
            lines = f"{r.get('start_line', '?')}-{r.get('end_line', '?')}"
            score = r.get("score", "")
            bridge.on_info(f"  {path}  L{lines}  score={score}")
        return

    if HAS_RICH:
        if not results:
            console.print(f"  [dim]RAG: нет результатов для '{query_text}'[/dim]")
            return
        table = Table(
            title=f"[bold]RAG: '{query_text}'[/bold]",
            box=box.ROUNDED, padding=(0, 1), border_style="cyan",
        )
        table.add_column("Файл", style="cyan", max_width=50)
        table.add_column("Строки", style="dim", width=10)
        table.add_column("Score", style="bold yellow", width=8, justify="right")
        table.add_column("Сниппет", style="dim", max_width=60)

        for r in results:
            path = _short_path(r.get("path", ""), 50)
            lines = f"{r.get('start_line', '?')}-{r.get('end_line', '?')}"
            score = str(r.get("score", ""))
            snippet = _truncate(r.get("snippet", ""), 60)
            table.add_row(path, lines, score, snippet)

        console.print(table)
    else:
        if not results:
            print(f"  RAG: нет результатов для '{query_text}'")
            return
        print(f"  RAG: '{query_text}' — {len(results)} результатов")
        for r in results:
            path = _short_path(r.get("path", ""), 50)
            print(f"    {path}  строки {r.get('start_line')}-{r.get('end_line')}  score={r.get('score')}")


def display_enhanced_status(
    model_name: str, profile: str, context_limit: int,
    human_count: int, ai_count: int, tool_count: int, total: int,
    rag_stats: Optional[Dict[str, Any]] = None,
    version_count: int = 0,
    session_start: Optional[float] = None,
    creator_active: bool = False,
) -> None:
    """Enhanced status panel with RAG, versioning, and creator mode info."""
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info(f"Модель: {model_name} ({profile})")
        bridge.on_info(f"Контекст: {context_limit:,} токенов")
        bridge.on_info(f"Сообщения: 👤 {human_count}  🤖 {ai_count}  🔧 {tool_count}  Σ {total}")
        if rag_stats and rag_stats.get("chunks"):
            bridge.on_info(f"RAG: {rag_stats['chunks']:,} чанков, {rag_stats['files']} файлов")
        if creator_active:
            bridge.on_info("Creator Mode: активен")
        bridge.on_status_update(model=model_name, tokens=f"{total} msgs")
        return

    if not HAS_RICH:
        display_status_panel(model_name, profile, context_limit,
                             human_count, ai_count, tool_count, total)
        if rag_stats:
            print(f"  RAG: {rag_stats.get('chunks', 0)} чанков, {rag_stats.get('files', 0)} файлов")
        if version_count:
            print(f"  Версии файлов: {version_count}")
        if creator_active:
            print(f"  Creator Mode: активен")
        return

    pct = 0
    if context_limit > 0:
        approx_tokens = total * 150
        pct = round(100 * approx_tokens / context_limit, 1)
    bar_len = 20
    filled = min(int(bar_len * pct / 100), bar_len)
    bar_color = "green" if pct < 50 else ("yellow" if pct < 80 else "red")
    bar = f"[{bar_color}]{'█' * filled}{'░' * (bar_len - filled)}[/{bar_color}] [dim]{pct}%[/dim]"

    model_link = f"[link=https://openrouter.ai/models/{model_name}]{model_name}[/link]"

    content = (
        f"  [dim]Модель:[/dim]    [bold cyan]{model_link}[/bold cyan]\n"
        f"  [dim]Профиль:[/dim]  [bold]{profile}[/bold]\n"
        f"  [dim]Контекст:[/dim] [bold]{context_limit:,}[/bold] токенов\n\n"
        f"  [dim]Сообщения:[/dim]\n"
        f"    [cyan]👤[/cyan] Пользователь  [bold]{human_count}[/bold]\n"
        f"    [green]🤖[/green] Ассистент      [bold]{ai_count}[/bold]\n"
        f"    [magenta]🔧[/magenta] Инструменты    [bold]{tool_count}[/bold]\n"
        f"    [dim]━━━━━━━━━━━━━━━━━━━━[/dim]\n"
        f"    [bold]Σ  Всего           {total}[/bold]\n\n"
        f"  [dim]Заполнение контекста:[/dim] {bar}"
    )

    if rag_stats and rag_stats.get("chunks"):
        content += (
            f"\n\n  [dim]RAG индекс:[/dim] [bold]{rag_stats['chunks']:,}[/bold] чанков, "
            f"[bold]{rag_stats['files']}[/bold] файлов"
        )

    if version_count:
        content += f"\n  [dim]Версии файлов:[/dim] [bold]{version_count}[/bold]"

    if creator_active:
        content += "\n  [dim]Creator Mode:[/dim] [bold green]активен[/bold green]"

    if session_start:
        import time
        elapsed = time.time() - session_start
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        content += f"\n  [dim]Время сессии:[/dim] [bold]{mins}м {secs}с[/bold]"

    console.print(
        Panel(
            content,
            title="[bold]  Статус сессии [/bold]",
            border_style="#8B5CF6",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )

    # Token usage chart via plotext
    if rag_stats and rag_stats.get("chunks"):
        try:
            import plotext as plt
            import io

            plt.clf()
            plt.theme("dark")
            labels = ["Chunks", "Files"]
            values = [rag_stats["chunks"], rag_stats["files"]]
            plt.bar(labels, values, color=[140, 92, 246])
            plt.title("RAG Index")
            plt.plotsize(40, 8)

            buf = io.StringIO()
            plt.savefig(buf)
            chart_text = buf.getvalue()
            if chart_text.strip():
                console.print(Panel(
                    chart_text,
                    title="[dim]RAG Index[/dim]",
                    border_style="#2D2D3D",
                    box=box.ROUNDED,
                ))
        except Exception:
            pass


def suggest_command(user_input: str) -> Optional[str]:
    """Suggest a command if user input looks like a mistyped command."""
    if not user_input.startswith("/"):
        return None

    known_commands = [
        "/help", "/exit", "/plan", "/status", "/profile", "/model",
        "/balance", "/credits", "/compact", "/versions", "/rollback",
        "/agent", "/custom", "/creator", "/ls", "/tree", "/rag",
    ]

    cmd = user_input.split()[0].lower()
    if cmd in known_commands:
        return None

    best_match = None
    best_score = 0

    for known in known_commands:
        common = sum(1 for a, b in zip(cmd, known) if a == b)
        if len(cmd) > 2 and cmd[1:3] in known:
            common += 2
        score = common / max(len(cmd), len(known))
        if score > best_score and score > 0.4:
            best_score = score
            best_match = known

    return best_match
