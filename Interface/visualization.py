"""
Красивый терминальный вывод для агента Lorne (classic CLI) — вдохновлён Claude Code.

Использует ``rich`` для панелей, подсветки, Markdown и прогресса; без Rich — plain ANSI.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console, Group
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

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[38;2;167;139;250m"
GREEN = "\033[38;2;16;185;129m"
YELLOW = "\033[38;2;245;158;11m"
MAGENTA = "\033[38;2;139;92;246m"
BLUE = "\033[38;2;139;92;246m"
RED = "\033[38;2;239;68;68m"
WHITE = "\033[38;2;229;231;235m"

_CLI_PALETTE: Dict[str, str] = {}
_cli_style_sig: str = ""

if HAS_RICH:
    console = Console(highlight=False)
    _console_err = Console(highlight=False, stderr=True)
else:
    console = None  # type: ignore[misc, assignment]
    _console_err = None  # type: ignore[misc, assignment]

try:
    from Interface.branding import (
        APP_CLI_SUBTITLE,
        APP_DISPLAY_NAME,
        APP_FULL_VERSION_LABEL,
        APP_VERSION,
        cli_attractor_block,
    )
except ImportError:
    APP_DISPLAY_NAME = "Lorne"
    APP_VERSION = "0.98"
    APP_FULL_VERSION_LABEL = f"v{APP_VERSION}"
    APP_CLI_SUBTITLE = "Terminal coding assistant"

    def cli_attractor_block() -> str:
        return "\n".join(("    ·   ", "   ··   ", "  ···   "))


def _hex_to_ansi24(hex_color: str) -> str:
    h = (hex_color or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return "\033[0m"
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"
    except ValueError:
        return "\033[0m"


def refresh_cli_ui_from_prefs(force: bool = False) -> None:
    """Перечитать cli_theme и cli_accent_color; обновить Rich Console и ANSI для plain-режима."""
    global console, CYAN, MAGENTA, BLUE, GREEN, YELLOW, RED, WHITE, _CLI_PALETTE, _cli_style_sig  # noqa: PLW0603
    try:
        from Interface.cli_theme import (
            DEFAULT_CLI_THEME_ID,
            cli_palette,
            resolve_cli_theme_name,
        )
        from Interface.ui_prefs import load_prefs

        if force:
            _cli_style_sig = ""

        prefs = load_prefs()
        tn = resolve_cli_theme_name(str(prefs.get("cli_theme") or DEFAULT_CLI_THEME_ID))
        ac = str(prefs.get("cli_accent_color") or "").strip()
        sig = f"{tn}|{ac}"
        if sig == _cli_style_sig and _CLI_PALETTE and not force:
            return
        _cli_style_sig = sig
        _CLI_PALETTE = cli_palette(tn, ac)
        pal = _CLI_PALETTE
        CYAN = _hex_to_ansi24(pal.get("accent2", "#A78BFA"))
        MAGENTA = _hex_to_ansi24(pal.get("accent", "#8B5CF6"))
        BLUE = MAGENTA
        GREEN = _hex_to_ansi24(pal.get("green", "#10B981"))
        YELLOW = _hex_to_ansi24(pal.get("yellow", "#F59E0B"))
        RED = _hex_to_ansi24(pal.get("red", "#EF4444"))
        WHITE = _hex_to_ansi24(pal.get("fg", "#E5E7EB"))
        if HAS_RICH:
            rich_theme = Theme(
                {
                    "info": pal["accent2"],
                    "success": f"bold {pal['green']}",
                    "warning": f"bold {pal['yellow']}",
                    "error": f"bold {pal['red']}",
                    "tool": f"bold {pal['accent']}",
                    "dim": pal["fg2"],
                    "accent": f"bold {pal['accent']}",
                    "header": f"bold {pal['fg']} on {pal['bg3']}",
                    "cmd": f"bold {pal['accent']}",
                    "cyan": pal.get("cyan", pal["accent2"]),
                    "blue": pal.get("blue", pal["accent"]),
                    "magenta": pal["accent"],
                    "step": pal["accent2"],
                    "rule": pal["accent"],
                    "border": pal["border"],
                    "muted": pal["fg2"],
                    "panel.border": pal["border"],
                }
            )
            console = Console(theme=rich_theme, highlight=False)
    except Exception:
        pass


def _cli_p() -> Dict[str, str]:
    try:
        refresh_cli_ui_from_prefs()
    except Exception:
        pass
    if _CLI_PALETTE:
        return _CLI_PALETTE
    from Interface.cli_theme import DEFAULT_CLI_THEME_ID, cli_palette

    return cli_palette(DEFAULT_CLI_THEME_ID, "")


try:
    refresh_cli_ui_from_prefs()
except Exception:
    pass

# ─── Лимиты контекста по моделям ──────────────────────────────────
# Built dynamically from AVAILABLE_MODELS in llm_provider to avoid
# maintaining two separate lists. Falls back to a static dict for models
# that are not in the curated list (e.g. custom OpenRouter model IDs).
DEFAULT_CONTEXT_LIMIT = 128_000

def _build_ctx_map() -> Dict[str, int]:
    # Rebuilt on every lookup so freshly added Ollama/OpenRouter custom models
    # (saved via UI prefs) expose their declared ctx immediately.
    result: Dict[str, int] = {}
    try:
        from Agent.llm_provider import get_available_models
        _models = get_available_models()
    except ImportError:
        _models = []
    for m in _models:
        try:
            ctx = int(m.get("ctx") or 0)
        except Exception:
            ctx = 0
        if ctx > 0:
            result[str(m["id"])] = ctx
    return result


def get_context_limit(model_name: str) -> int:
    ctx_map = _build_ctx_map()
    if model_name in ctx_map:
        return ctx_map[model_name]
    # Ollama custom models registered as `ollama/<name>` — accept a suffix
    # match against the configured map.
    if (model_name or "").startswith("ollama/"):
        wire = model_name.split("/", 1)[1]
        for key, limit in ctx_map.items():
            if key.endswith("/" + wire) or key == wire:
                return limit
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


# CLI progress footer (round + plan step) — updated from round_header / plan_tool results.
_CLI_PROGRESS: Dict[str, Any] = {"round": 0, "step": None, "total": None, "title": ""}


def _emit_cli_progress_footer() -> None:
    if not HAS_RICH:
        return
    bridge = _get_tui_bridge()
    if bridge:
        r = int(_CLI_PROGRESS.get("round") or 0)
        si = _CLI_PROGRESS.get("step")
        st = _CLI_PROGRESS.get("total")
        ti = str(_CLI_PROGRESS.get("title") or "")
        parts = [f"Раунд {r}"]
        if si is not None:
            tot = f"/{st}" if st is not None else ""
            parts.append(f"шаг {si}{tot}")
        if ti:
            parts.append(ti[:56] + ("…" if len(ti) > 56 else ""))
        bridge.on_info(" · ".join(parts))
        return

    r = int(_CLI_PROGRESS.get("round") or 0)
    si = _CLI_PROGRESS.get("step")
    st = _CLI_PROGRESS.get("total")
    ti = str(_CLI_PROGRESS.get("title") or "")
    pal = _cli_p()
    line = Text()
    line.append("Раунд ", style="bold")
    line.append(str(r), style="bold cyan")
    if si is not None:
        line.append("    Шаг ", style="bold")
        tot = f"/{st}" if st is not None else ""
        line.append(f"{si}{tot}", style="bold yellow")
    if ti:
        line.append("    ", style="")
        line.append((ti[:52] + "…") if len(ti) > 52 else ti, style="dim")
    console.print(
        Panel(
            line,
            title="[bold]Прогресс[/bold]",
            title_align="left",
            border_style=pal.get("accent2", pal.get("accent", "magenta")),
            box=box.HEAVY,
            padding=(0, 1),
        )
    )


def set_cli_progress_round(n: int) -> None:
    _CLI_PROGRESS["round"] = int(n)


def set_cli_progress_plan_step(step: Optional[int], total: Optional[int] = None, title: str = "") -> None:
    _CLI_PROGRESS["step"] = step
    _CLI_PROGRESS["total"] = total
    if title:
        _CLI_PROGRESS["title"] = title


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
        console.print(Rule(f"[bold]{title}[/bold]", style=_cli_p()["accent"]))
        console.print()
    else:
        line = char * min(60, len(title) + 6)
        print(f"\n{DIM}{line}{RESET}")
        print(f"{BOLD}{title}{RESET}")
        print(f"{DIM}{line}{RESET}")


def step(num: int, title: str, detail: str = "") -> None:
    if HAS_RICH:
        marker = f"[step]●[/step] [bold]Шаг {num}[/bold]: {title}"
        if detail:
            marker += f"  [dim]{detail}[/dim]"
        console.print(marker)
    else:
        print(f"\n{CYAN}● Шаг {num}: {title}{RESET}")
        if detail:
            print(f"   {DIM}{detail}{RESET}")


def round_header(round_num: int) -> None:
    set_cli_progress_round(round_num)
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_separator(f"Round {round_num}")
        return
    if HAS_RICH:
        console.print()
        _rh = _cli_p()
        rn = max(1, int(round_num))
        console.print(
            Panel(
                f"[bold white] {rn} [/bold white]",
                title="[bold]Раунд[/bold]",
                title_align="center",
                border_style=_rh["accent"],
                box=box.HEAVY,
                padding=(0, 2),
                width=16,
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

    if name == "plan_tool" and isinstance(args, dict):
        args = dict(args)
        sj = args.get("steps_json")
        if isinstance(sj, str) and len(sj) > 120:
            args["steps_json"] = f"<{len(sj)} симв.>"
        elif sj is not None and not isinstance(sj, str):
            args["steps_json"] = f"<{len(str(sj))} симв.>"

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
        _aa = _cli_p()
        tool_text = Text()
        tool_text.append("⚡ ", style="yellow")
        tool_text.append(name, style="bold magenta")

        panel_content = Text(args_str, style="dim")
        console.print(
            Panel(
                panel_content,
                title=tool_text,
                title_align="left",
                border_style=_aa["accent"],
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

    if name in ("save_plan", "update_plan", "load_plan", "clear_plan", "plan_tool"):
        if name == "plan_tool" and isinstance(result, dict):
            inner = str(result.get("_plan_action") or "load_plan")
            sub = {k: v for k, v in result.items() if k != "_plan_action"}
            _display_plan_result(inner, sub)
        else:
            _display_plan_result(name, result)
        return

    if name == "read_file" and isinstance(result, dict):
        _display_read_file_result(result)
        return

    if name == "read_file_lines" and isinstance(result, dict):
        _display_read_file_lines_result(result)
        return

    if name == "run_package_script" and isinstance(result, dict):
        _display_package_script_result(result)
        return

    if name == "run_command" and isinstance(result, dict):
        _display_command_result(result)
        return

    if name in ("edit_file", "write_file", "create_code_file", "append_code_snippet", "code_file_tool"):
        _display_file_change_result(name, result)
        return

    if name == "list_files" and isinstance(result, dict):
        _display_list_files_result(result)
        return

    if name == "search_in_files" and isinstance(result, dict):
        _display_search_result(result)
        return

    if name == "find_in_file" and isinstance(result, dict):
        _display_find_in_file_result(result)
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
                si = result.get("step_index")
                note = (result.get("note") or "").strip()
                set_cli_progress_plan_step(
                    int(si) if si is not None else None,
                    None,
                    note[:80] if note else f"статус: {status}",
                )
                pal = _cli_p()
                line = f"[bold]{icon} План · шаг {si}[/bold] → [yellow]{status}[/yellow]"
                if note:
                    line += f"\n[dim]{note}[/dim]"
                console.print(
                    Panel(
                        line,
                        title="[bold]План[/bold]",
                        title_align="left",
                        border_style=pal["accent"],
                        box=box.HEAVY,
                        padding=(0, 1),
                    )
                )
                _emit_cli_progress_footer()
            else:
                console.print(f"  [warning]Ошибка плана: {result.get('error')}[/warning]")
        elif name == "load_plan":
            plan = result.get("plan") or {}
            if not result.get("ok"):
                console.print("  [dim]Нет активного плана[/dim]")
                return
            steps = plan.get("steps") or []
            if isinstance(steps, list) and steps:
                set_cli_progress_plan_step(
                    None,
                    len(steps),
                    str(plan.get("title", ""))[:80],
                )
            table = Table(title=plan.get("title", "План"), box=box.SIMPLE, show_header=False, padding=(0, 1))
            table.add_column("Статус", width=3)
            table.add_column("Шаг")
            for s in (plan.get("steps") or [])[:15]:
                status = s.get("status", "pending")
                icon = {"completed": "[green]✓[/green]", "in_progress": "[yellow]▶[/yellow]", "blocked": "[red]⚠[/red]"}.get(status, "[dim]○[/dim]")
                table.add_row(icon, s.get("text", ""))
            console.print(table)
            _emit_cli_progress_footer()
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
        syntax_theme = "monokai"
        try:
            from Interface.ui_prefs import load_prefs
            _syn = str(load_prefs().get("syntax_theme", "monokai"))
            syntax_theme = {
                "monokai": "monokai",
                "dracula": "dracula",
                "github_dark": "github-dark",
                "github_light": "github-light",
                "vs_dark": "vscode-dark",
                "vscode_dark": "vscode-dark",
                "nord": "nord",
                "one_dark": "one-dark",
                "one_light": "one-light",
                "material": "material",
                "zenburn": "zenburn",
                "solarized_dark": "solarized-dark",
                "solarized_light": "solarized-light",
            }.get(_syn, "monokai")
        except Exception:
            pass
        _pv = _cli_p()
        console.print(
            Panel(
                Syntax(preview, lang, theme=syntax_theme, line_numbers=True, word_wrap=True),
                title=f"[bold]{short}[/bold] [dim]({total} строк)[/dim]",
                title_align="left",
                border_style=_pv["cyan"],
                box=box.ROUNDED,
                padding=(0, 0),
            )
        )
    else:
        print(f"   {DIM}Прочитано: {_short_path(path)}  ({total} строк){RESET}")


def _display_read_file_lines_result(result: Dict[str, Any]) -> None:
    path = result.get("file_path", "") or result.get("path", "")
    content = result.get("content", "")
    total = int(result.get("total_lines") or 0)
    show = result.get("showing") or ""
    if result.get("error"):
        if HAS_RICH:
            console.print(f"  [red]read_file_lines: {result.get('error')}[/red]  {_short_path(path)}")
        return

    if HAS_RICH:
        short = _short_path(path)
        lang = _detect_language(path)
        preview = content[:4000] if len(content) > 4000 else content
        if preview != content:
            preview += "\n… (обрезано)"
        syntax_theme = "monokai"
        try:
            from Interface.ui_prefs import load_prefs

            _syn = str(load_prefs().get("syntax_theme", "monokai"))
            syntax_theme = {
                "monokai": "monokai",
                "dracula": "dracula",
                "github_dark": "github-dark",
            }.get(_syn, "monokai")
        except Exception:
            pass
        _pv = _cli_p()
        sub = f"{total} строк в файле"
        if show:
            sub += f" · {show}"
        console.print(
            Panel(
                Syntax(preview, lang, theme=syntax_theme, line_numbers=True, word_wrap=True),
                title=f"[bold]{short}[/bold] [dim](read_file_lines)[/dim]",
                subtitle=f"[dim]{sub}[/dim]",
                title_align="left",
                border_style=_pv["cyan"],
                box=box.ROUNDED,
                padding=(0, 0),
            )
        )
    else:
        print(f"   {DIM}{_short_path(path)}  {show}{RESET}")


def _display_package_script_result(result: Dict[str, Any]) -> None:
    if not HAS_RICH:
        rc = result.get("returncode", -1)
        print(f"   script: {result.get('script')} rc={rc}")
        return
    pal = _cli_p()
    ok = bool(result.get("ok"))
    rc = result.get("returncode", -1)
    st = "успех" if ok else "ошибка"
    out = (result.get("stdout") or "")[:3500]
    err = (result.get("stderr") or "")[:2500]
    chunks: List[str] = []
    if out.strip():
        chunks.append(out + ("\n" if len((result.get("stdout") or "")) > 3500 else ""))
    if err.strip():
        chunks.append(f"[red]{err}[/red]")
    body = "\n".join(chunks) if chunks else "[dim](нет вывода)[/dim]"
    style = pal.get("green", "green") if ok else "red"
    console.print(
        Panel(
            body,
            title=f"[bold]{result.get('package_manager', 'npm')} run {result.get('script', '?')}[/bold]  [{st} · exit {rc}]",
            title_align="left",
            border_style=style,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def _display_command_result(result: Dict[str, Any]) -> None:
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    rc = result.get("returncode", -1)
    skipped = result.get("skipped", False)
    background = bool(result.get("background"))

    if HAS_RICH:
        if background and not skipped:
            pal = _cli_p()
            pid = result.get("pid", "")
            logp = result.get("log_path", "")
            msg = (result.get("stdout") or "").strip()
            console.print(
                Panel(
                    f"{msg}\n[dim]pid={pid} · log: {logp}[/dim]",
                    title="[bold]Фоновая команда[/bold]",
                    title_align="left",
                    border_style=pal.get("green", "green"),
                    box=box.HEAVY,
                    padding=(0, 1),
                )
            )
            return
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
        _lv = _cli_p()
        console.print(
            Panel(
                cols,
                title=f"[bold]{_short_path(path)}[/bold] [dim]({len(entries)} элементов)[/dim]",
                title_align="left",
                border_style=_lv["cyan"],
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


def _display_find_in_file_result(result: Dict[str, Any]) -> None:
    err = result.get("error")
    if err:
        if HAS_RICH:
            console.print(f"  [warning]find_in_file: {err}[/warning] — {result.get('file_path', '')}")
        else:
            print(f"   find_in_file: {err}")
        return
    matches = result.get("matches", [])
    pat = str(result.get("pattern", ""))[:80]
    fp = _short_path(str(result.get("file_path", "")), 56)
    if HAS_RICH:
        if not matches:
            console.print(f"  [dim]find_in_file: нет совпадений «{pat}» в {fp}[/dim]")
            return
        table = Table(
            title=f"find_in_file «{pat}» · {fp}",
            box=box.SIMPLE,
            padding=(0, 1),
        )
        table.add_column("Стр.", style="dim", justify="right")
        table.add_column("Текст", style="default")
        for m in matches[:40]:
            ln = m.get("line", "")
            tx = _truncate(str(m.get("text", "")), 200)
            table.add_row(str(ln), tx)
        console.print(table)
        if result.get("truncated"):
            console.print("  [dim]… обрезано по max_matches[/dim]")
    else:
        print(f"   find_in_file: {fp} — {len(matches)} совпад.")
        for m in matches[:20]:
            print(f"     L{m.get('line', '')}: {_truncate(str(m.get('text', '')), 120)}")


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
        _mr = _cli_p()
        _gborder = _mr.get("green", "green")
        try:
            md = RichMarkdown(clean_content)
            console.print(
                Panel(
                    md,
                    title="[bold white]Ассистент[/bold white]",
                    title_align="left",
                    border_style=_gborder,
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
                    border_style=_gborder,
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

def _cli_hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (139, 92, 246)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (139, 92, 246)


def print_startup_banner(
    model_name: str,
    profile: str,
    project_name: str,
    balance: str = "",
    mode_label: str = "Classic CLI",
    version: str = APP_VERSION,
) -> None:
    """Стартовый баннер classic CLI: аттрактор слева, figlet имени, метаданные сессии."""
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info(
            f"{APP_DISPLAY_NAME} — {model_name} ({profile}) | Project: {project_name}",
        )
        if balance:
            bridge.on_info(f"Balance: {balance}")
        return

    _bc = _cli_p()
    logo_block: Any = ""
    try:
        from pyfiglet import figlet_format

        raw = figlet_format(APP_DISPLAY_NAME, font="slant")
        logo_lines = Text()
        lines = raw.splitlines()
        n = max(1, len(lines))
        r1, g1, b1 = _cli_hex_rgb(_bc["accent"])
        r2, g2, b2 = _cli_hex_rgb(_bc["accent2"])
        for i, line in enumerate(lines):
            t = (i + 1) / float(n)
            rr = int(r1 + (r2 - r1) * t)
            gg = int(g1 + (g2 - g1) * t)
            bb = int(b1 + (b2 - b1) * t)
            logo_lines.append(line + "\n", style=f"bold rgb({rr},{gg},{bb})")
        logo_block = logo_lines
    except Exception:
        logo_block = Text(f"  {APP_DISPLAY_NAME}\n", style=f"bold {_bc['accent']}")

    attractor = Text(cli_attractor_block() + "\n", style=f"bold {_bc['accent2']}")

    sub = Text()
    sub.append(f"  {APP_CLI_SUBTITLE}", style=f"bold {_bc['accent2']}")
    sub.append(f"  {APP_FULL_VERSION_LABEL}\n", style=_bc["fg2"])
    sub.append("  " + "─" * 28 + "\n", style=_bc["border"])

    meta = Text()
    meta.append("  Модель:   ", style="dim")
    meta.append(f"{model_name}\n", style=f"bold {_bc['accent']}")
    meta.append("  Профиль: ", style="dim")
    meta.append(f"{profile}\n", style=f"bold {_bc['fg']}")
    meta.append("  Проект:  ", style="dim")
    meta.append(f"{project_name}\n", style=f"bold {_bc['fg']}")
    if balance:
        meta.append("  Баланс:  ", style="dim")
        meta.append(f"{balance}\n", style=f"bold {_bc['green']}")
    meta.append("  Режим:   ", style="dim")
    meta.append(f"{mode_label}\n", style=f"bold {_bc['cyan']}")
    meta.append("  Подсказка: ", style="dim")
    meta.append("@file автодополнение, /help команды\n", style=_bc["fg"])

    if HAS_RICH and console:
        from rich.console import Group

        logo_row = Columns([attractor, logo_block], padding=(0, 2), expand=False)
        inner = Group(logo_row, sub, meta)
        console.print()
        console.print(
            Panel(
                inner,
                border_style=_bc["border"],
                box=box.HEAVY,
                padding=(1, 2),
            )
        )
        console.print()
    else:
        print(f"\n{'═' * 50}")
        print(cli_attractor_block())
        print(f"  {APP_DISPLAY_NAME} — {APP_CLI_SUBTITLE} {APP_FULL_VERSION_LABEL}")
        print(f"  Модель:   {model_name}")
        print(f"  Профиль:  {profile}")
        print(f"  Проект:   {project_name}")
        if balance:
            print(f"  Баланс:  {balance}")
        print(f"  Режим:    {mode_label}")
        print(f"{'═' * 50}\n")


def print_welcome(model_name: str, profile: str, project_name: str, balance: str = "") -> None:
    """Обратная совместимость: тот же вид, что стартовый баннер (без дублирования логики)."""
    print_startup_banner(model_name, profile, project_name, balance=balance, mode_label="Classic CLI")


def display_shell_command(command: str) -> None:
    """Display a user-initiated shell command with terminal-like styling."""
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_action("shell", command)
        return
    if HAS_RICH:
        _sh = _cli_p()
        console.print(
            Panel(
                Text.assemble(
                    ("❯ ", f"bold {_sh['green']}"),
                    (command, "bold white"),
                ),
                title=f"[bold {_sh['green']}]  Terminal [/bold {_sh['green']}]",
                title_align="left",
                border_style=_sh["green"],
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

    _tp = _cli_p()
    table = Table(
        box=box.ROUNDED,
        border_style=_tp["accent"],
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
    _sp = _cli_p()

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
            border_style=_sp["accent"],
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


_HELP_CATEGORIES = [
    ("Базовые", [
        ("/help", "Эта справка"),
        ("/exit", "Выход из Lorne"),
        ("/status", "Статус сессии: модель, сообщения, RAG"),
        ("/compact", "Сжать историю для экономии контекста"),
        ("!<shell-command>", "Выполнить shell-команду напрямую"),
    ]),
    ("Модели", [
        ("/model", "Выбор модели: номер из списка или /model <id>"),
        ("/model <id>", "Установить модель по ID (OpenRouter и др.)"),
        ("/profile [fast|balanced|quality]", "Профиль: температура и лимиты токенов"),
        ("/balance", "Баланс OpenRouter"),
        ("/credits", "То же, что /balance"),
    ]),
    ("Проект/навигация", [
        ("/ls [path]", "Список файлов в каталоге"),
        ("/tree [path]", "Дерево проекта"),
        ("/rag <query>", "Семантический поиск по проекту (RAG)"),
        ("/plan", "Показать текущий план задачи"),
    ]),
    ("Git", [
        ("/git status", "Статус репозитория"),
        ("/git log [path]", "История коммитов (опционально по файлу)"),
        ("/git diff [hash]", "Diff текущих изменений или коммита"),
        ("/git rollback <hash>", "Откатить коммит (revert)"),
        ("/git branch", "Текущая ветка"),
    ]),
    ("Версии/история", [
        ("/versions <file>", "История версий файла (SQLite)"),
        ("/rollback <file> [version_id]", "Откатить файл к версии из SQLite"),
    ]),
    ("Custom tools", [
        ("/custom", "Список кастомных инструментов"),
        ("/custom list", "То же, что /custom"),
        ("/custom add <name>", "Добавить свой тул (код вводится после команды)"),
        ("/custom remove <name>", "Удалить кастомный тул"),
        ("/custom reload", "Перезагрузить кастомные тулы"),
    ]),
    ("Creator", [
        ("/creator", "Включить Creator mode (как /creator on)"),
        ("/creator on|off", "Включить или выключить Creator mode"),
        ("/creator config", "Показать конфигурацию Creator"),
        ("/creator set <local_model|local_base_url|max_workers|orchestration> <value>", "Изменить параметр Creator"),
        ("/creator <task>", "Запустить задачу в Creator mode"),
    ]),
    ("Research", [
        ("/research on|off|status", "Включить/выключить или статус Research mode"),
        ("/research <query>", "Исследование по теме (веб + источники)"),
    ]),
    ("Deep", [
        ("/deep", "Режим Deep Solver (как /deepmode)"),
        ("/deep <запрос>", "Сразу цель Deep (режим deep + запуск с этой задачей)"),
        ("/deepmode", "Включить режим Deep Solver (локальный долгий цикл)"),
        ("/mode deep", "То же через /mode"),
        ("/deepcp list", "Список активных Deep checkpoint"),
        ("/deepcp rollback <checkpoint_id>", "Откат к checkpoint Deep Solver"),
        ("/deepcp continue <checkpoint_id>", "Продолжить от checkpoint"),
        ("/stop", "Остановить текущее выполнение агента"),
    ]),
    ("Ollama", [
        ("/model ollama", "Выбор модели: список с сервера → номер или тег; см. /ollama pick"),
        ("/model ollama/<тег>", "Сразу активировать модель, напр. ollama/llama3.2:latest"),
        ("/ollama pick", "То же интерактивное меню выбора модели"),
        ("/ollama [help]", "Список подкоманд (то же без аргумента)"),
        ("/ollama status", "Какие модели сейчас загружены в память (running)"),
        ("/ollama list", "Все теги моделей с сервера + заявленный ctx"),
        ("/ollama refresh", "Перезапросить список с сервера"),
        ("/ollama set-url <url>", "OpenAI-совместимый base URL (часто …/v1), пишется в .lorne/ui_settings.json (или legacy .tca)."),
        ("/ollama set-key <key>", "Bearer/API-ключ для прокси; пустая строка сбрасывает"),
        ("/ollama add-model <name> [ctx]", "Добавить модель в локальный список выбора; ctx — контекст по умолчанию"),
        ("/ollama remove-model <name>", "Убрать из списка и очистить model-set для неё"),
        ("/ollama preset-list", "Имена пресетов из ollama_presets (по умолчанию есть default)"),
        ("/ollama preset-set <model> <preset>", "Скопировать все поля пресета в настройки модели"),
        ("/ollama model-set <model> <k=v,...>", "Точечно: см. блок «Подробнее» при /help ollama"),
    ]),
    ("Персонализация", [
        ("/theme [list]", "Список тем CLI или /theme <id>: purple, void, ice, matrix, paper, …"),
        ("/accent <аргумент>", "Основной акцент CLI → cli_accent_color (#hex или F1–F8)"),
    ]),
]


# Совпадает с Agent.command_router.CommandRouter._handle_accent (ansi_map).
_ACCENT_F_PRESETS: List[tuple[str, str, str]] = [
    ("F1", "#8B5CF6", "фиолетовый"),
    ("F2", "#10B981", "изумрудный"),
    ("F3", "#F59E0B", "янтарный"),
    ("F4", "#EF4444", "красный"),
    ("F5", "#3B82F6", "синий"),
    ("F6", "#A78BFA", "светло-фиолетовый"),
    ("F7", "#22C55E", "зелёный"),
    ("F8", "#F97316", "оранжевый"),
]


def _theme_accent_merged_detail_lines() -> List[str]:
    """Единый текст для /help theme, /help accent и секции «Персонализация»."""
    try:
        from Interface.cli_theme import ALL_CLI_THEME_IDS
    except Exception:
        ALL_CLI_THEME_IDS = []

    lines = [
        "Тема CLI (/theme) и акцент (/accent) задаются отдельно от оформления Textual TUI.",
        "В конфиге: короткий id в cli_theme и опционально cli_accent_color (.lorne/ui_settings.json или legacy .tca).",
        "Старые имена из TUI (Purple Dark, Monokai, …) маппятся в ближайший CLI-пресет.",
        "",
        "Доступные id темы:",
    ]
    for name in ALL_CLI_THEME_IDS:
        lines.append(f"  • {name}")
    lines.extend([
        "",
        "/theme или /theme list — показать список; /theme <id> — применить пресет.",
        "После смены темы обновляются рамки панелей, semantic-стили Rich (success/warning/error),",
        "цвета cyan/blue/magenta в разметке и escape-последовательности в plain-режиме без Rich.",
        "",
        "/accent задаёт только основной акцент; secondary (accent2), границы и «характер» темы сохраняются.",
        "",
        "Быстрые пресеты /accent (регистр не важен):",
    ])
    for fk, hx, ru in _ACCENT_F_PRESETS:
        lines.append(f"  {fk} → {hx}  ({ru})")
    lines.extend([
        "Также можно указать #RRGGBB или #RGB.",
        "",
        "Примеры:",
        "  /theme ice",
        "  /theme void",
        "  /accent F2",
        "  /accent #10B981",
    ])
    return lines


def _ollama_help_detail_lines() -> List[str]:
    return [
        "Как выбрать модель Ollama в CLI:",
        "  1) /model ollama  или  /ollama pick — таблица моделей (как у OpenRouter): номер, тег, ctx;",
        "     затем введи номер строки или полный тег.",
        "  2) /model ollama/имя:тег — сразу без меню (имя как в «ollama list» или /ollama list).",
        "  3) /ollama list — только посмотреть теги; затем пункт 1 или 2.",
        "После выбора модель добавляется в общий список /model и сохраняется в настройках.",
        "",
        "По умолчанию base URL: http://localhost:11434/v1 (меняется через /ollama set-url).",
        "Ключ и URL пишутся в .lorne/ui_settings.json (ollama_base_url, ollama_api_key; legacy .tca).",
        "",
        "Пресеты (ollama_presets): в preset-list видны имена; у встроенного «default» поля:",
        "  temperature, top_p, top_k, repeat_penalty, num_ctx, num_predict, stop",
        "",
        "/ollama model-set <модель> <список> — пары key=value через запятую, без пробелов вокруг «=».",
        "Поддерживаемые ключи (как в роутере):",
        "  float:  temperature, top_p, repeat_penalty",
        "  int:    top_k, num_ctx, num_predict",
        "  str:    stop, preset",
        "",
        "Примеры:",
        "  /ollama set-url http://127.0.0.1:11434/v1",
        "  /ollama add-model llama3.2:latest 8192",
        "  /ollama model-set llama3.2:latest temperature=0.35,num_ctx=16384,top_p=0.9",
        "  /ollama preset-set llama3.2:latest default",
        "  /ollama remove-model llama3.2:latest",
    ]


def _canonical_section_key(name: str) -> str:
    return " ".join(name.strip().lower().replace("/", " ").split())


# Синонимы темы → имя секции из _HELP_CATEGORIES (латиница/транслит по смыслу).
_SECTION_TOPIC_ALIASES: Dict[str, str] = {
    "базовые": "Базовые",
    "basic": "Базовые",
    "модели": "Модели",
    "модель": "Модели",
    "model": "Модели",
    "models": "Модели",
    "проект": "Проект/навигация",
    "навигация": "Проект/навигация",
    "проект навигация": "Проект/навигация",
    "navigation": "Проект/навигация",
    "git": "Git",
    "версии": "Версии/история",
    "история": "Версии/история",
    "версии история": "Версии/история",
    "versions": "Версии/история",
    "custom": "Custom tools",
    "custom tools": "Custom tools",
    "тулы": "Custom tools",
    "кастом": "Custom tools",
    "creator": "Creator",
    "создатель": "Creator",
    "research": "Research",
    "исследование": "Research",
    "исследования": "Research",
    "deep": "Deep",
    "глубоко": "Deep",
    "checkpoint": "Deep",
    "checkpoints": "Deep",
    "deepcp": "Deep",
    "ollama": "Ollama",
    "персонализация": "Персонализация",
    "тема": "Персонализация",
    "theme": "Персонализация",
}


def _resolve_topic_to_help_section(topic: str) -> Optional[str]:
    """Имя секции из _HELP_CATEGORIES или None. Узкие темы accent/acsent не сюда."""
    t = _canonical_section_key(topic)
    if not t:
        return None
    if t in _SECTION_TOPIC_ALIASES:
        return _SECTION_TOPIC_ALIASES[t]
    for cat_name, _ in _HELP_CATEGORIES:
        if t == _canonical_section_key(cat_name):
            return cat_name
    return None


def _help_section_detail_lines(section_name: str) -> List[str]:
    """Подробный текст для /help <секция>."""
    if section_name == "Ollama":
        return _ollama_help_detail_lines()

    sections: Dict[str, List[str]] = {
        "Базовые": [
            "Общие команды сессии и оболочки.",
            "",
            "/help [тема] — полный список или фильтр по слову; /help базовые, /help модели, …",
            "Справка выводится одним блоком: таблица команд и раздел «подробнее» ниже разделителем.",
            "/exit — выход из Lorne (сохранение зависит от режима).",
            "/status — модель, профиль, лимит контекста, счётчики сообщений и при наличии — RAG.",
            "/compact — сжать историю через compact_conversation (оставляет последние сообщения);",
            "  полезно, когда контекст переполнен. После сжатия состояние может сохраниться.",
            "!<cmd> — выполнить shell-команду в проекте (таймаут и безопасность — см. Terminal.runner).",
        ],
        "Модели": [
            "Выбор LLM и профиля генерации (температура, лимиты токенов — через init_llm).",
            "",
            "/model — интерактивный выбор из списка или ввод номера;",
            "/model <id> — прямой ID (OpenRouter, кастомные ID из настроек, Ollama после добавления).",
            "/profile [fast|balanced|quality] — без аргумента показывает текущий и доступные профили;",
            "  с аргументом переключает профиль и переинициализирует LLM.",
            "/balance и /credits — баланс/кредиты OpenRouter (если провайдер это поддерживает);",
            "  в CLI под текстом счёта показывается календарь расходов по дням (локальный лог .lorne/openrouter_usage.json или legacy .tca).",
            "",
            "Ollama: /model ollama или /model ollama/<тег> — см. /help ollama.",
        ],
        "Проект/навигация": [
            "Просмотр файловой структуры и RAG по рабочей области.",
            "",
            "/ls [path] — плоский список файлов (по умолчанию «.»); путь относительно workspace.",
            "/tree [path] — дерево каталогов через analyze_project_structure.",
            "/rag <запрос> — семантический поиск по индексу (top_k≈10), затем краткая статистика индекса.",
            "/plan — загрузить и показать текущий план задачи (plan_tool).",
        ],
        "Git": [
            "Обёртка над репозиторием в cwd (нужны GitPython и инициализированный git).",
            "",
            "/git или /git status — ветка, чистота, списки changed / staged / untracked.",
            "/git log [path] — последние коммиты (до ~15); path ограничивает лог по файлу.",
            "/git diff [hash] — diff рабочей копии или с указанным коммитом (вывод усечён в терминале).",
            "/git rollback <hash> — отмена коммита через git integration (revert-логика менеджера).",
            "/git branch — имя текущей ветки.",
            "",
            "Если «Git не инициализирован» — git init в проекте или открой другой каталог.",
        ],
        "Версии/история": [
            "Версии файлов в локальной SQLite (не путать с git).",
            "",
            "/versions <file> — запрос к агенту показать версии через инструмент list_file_versions.",
            "/rollback <file> [version_id] — откат содержимого через rollback_file;",
            "  пустой version_id может означать последнюю/подсказку от тула — см. сообщение роутера.",
            "",
            "Путь к файлу — относительно workspace.",
        ],
        "Custom tools": [
            "Пользовательские инструменты (@tool), хранятся на диске и подмешиваются в агента.",
            "",
            "/custom или /custom list — таблица имён и описаний.",
            "/custom add <name> — многострочный ввод кода (пустая строка завершает); можно шаблон по Enter.",
            "/custom remove <name> — удалить файл тула и перезагрузить реестр.",
            "/custom reload — перечитать кастомные тулы без перезапуска приложения.",
            "",
            "После изменений список tools в сессии обновляется (refresh_runtime_tools).",
        ],
        "Creator": [
            "Режим параллельных под-агентов с локальной «тяжёлой» моделью (конфиг в creator_config).",
            "",
            "/creator или /creator on — включить creator_mode, переключить режим на creator, проверить сервер.",
            "/creator off — выключить и вернуть режим в normal.",
            "/creator config — локальная модель, base URL, воркеры, orchestration (parallel|sequential|…).",
            "/creator set <ключ> <значение> — local_model, local_base_url, max_workers, orchestration;",
            "  orchestration: parallel | sequential | supervisor | hierarchical.",
            "/creator <текст> — одна строка задачи: run_creator_mode, итог в чат и сохранение.",
            "",
            "Локальный сервер недоступен — предупреждение и возможный fallback на heavy-модель.",
        ],
        "Research": [
            "Режим с упором на веб-поиск и синтез источников.",
            "",
            "/research on|off — флаг research_mode; on также вызывает set_mode(research).",
            "/research status — состояние режима.",
            "/research <query> — длинный промпт с инструкцией использовать web_search, context7 и т.д.;",
            "  запускается run_and_render как обычное сообщение.",
            "",
            "Лимиты источников/раундов задаются в ui_prefs (research_max_sources, research_max_rounds, …).",
        ],
        "Deep": [
            "Deep Solver: длинные цепочки рассуждения с контрольными точками.",
            "",
            "/deepcp list — id, turn_index, title активных checkpoint (из контекста get_deep_checkpoints).",
            "/deepcp rollback <id> — откат состояния к checkpoint.",
            "/deepcp continue <id> — продолжить ветку от checkpoint.",
            "/stop — выставить stop_requested[0]=True, чтобы прервать текущий прогон графа агента.",
            "",
            "Если API checkpoint недоступен, роутер сообщит об ошибке.",
        ],
        "Персонализация": [],  # текст выдаётся через _theme_accent_merged_detail_lines()
    }
    return sections.get(section_name, [])


def _help_topic_wants_theme_accent_merged(topic: str) -> bool:
    t = (topic or "").strip().lower()
    return t in (
        "theme", "тема", "cli_theme", "cli theme",
        "accent", "acsent", "акцент",
    )


def _help_topic_detail_lines_for_topic(topic: str) -> List[str]:
    if _help_topic_wants_theme_accent_merged(topic):
        return _theme_accent_merged_detail_lines()
    if _help_topic_wants_ollama_detail(topic):
        return _ollama_help_detail_lines()
    sec = _resolve_topic_to_help_section(topic)
    if sec == "Персонализация":
        return _theme_accent_merged_detail_lines()
    if sec:
        return _help_section_detail_lines(sec)
    return []


def _help_topic_wants_ollama_detail(topic: str) -> bool:
    return "ollama" in (topic or "").strip().lower()


def _help_search_tokens(topic: str) -> List[str]:
    t = (topic or "").strip().lower()
    if not t:
        return []
    tokens = [t]
    if t == "accent":
        tokens.append("acsent")
    elif t == "acsent":
        tokens.append("accent")
    return tokens


def _filter_help_categories(topic: str) -> List[tuple[str, List[tuple[str, str]]]]:
    tokens = _help_search_tokens(topic)
    if not tokens:
        return []
    out: List[tuple[str, List[tuple[str, str]]]] = []
    for cat_name, cmds in _HELP_CATEGORIES:
        cn = cat_name.lower()
        if any(tok in cn for tok in tokens):
            out.append((cat_name, list(cmds)))
            continue
        rows: List[tuple[str, str]] = []
        for cmd, desc in cmds:
            blob = f"{cmd} {desc}".lower()
            if any(tok in blob for tok in tokens):
                rows.append((cmd, desc))
        if rows:
            out.append((cat_name, rows))
    return out


def print_help_topic(topic: str) -> None:
    """Показать строки справки, где встречается topic (команда или описание)."""
    refresh_cli_ui_from_prefs()
    filtered = _filter_help_categories(topic)
    if not filtered:
        print_info(
            f"По запросу «{(topic or '').strip()}» совпадений в справке нет. "
            "Введите /help без аргумента для полного списка."
        )
        return

    detail_lines = _help_topic_detail_lines_for_topic(topic)
    q = (topic or "").strip()

    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info(f"── Справка: {q} ──")
        for cat_name, cmds in filtered:
            bridge.on_info(f"── {cat_name} ──")
            for cmd, desc in cmds:
                bridge.on_info(f"  {cmd:<24} {desc}")
        if detail_lines:
            for ln in detail_lines:
                bridge.on_info(ln)
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
        _hp = _cli_p()
        for cat_name, cmds in filtered:
            table.add_row(f"\n[bold]{cat_name}[/bold]", "")
            for cmd, desc in cmds:
                table.add_row(f"  [cmd]{cmd}[/cmd]", desc)
        if detail_lines:
            inner = Group(
                table,
                Rule(style=_hp["accent"]),
                Text("\n".join(detail_lines), style=_hp["fg2"]),
            )
        else:
            inner = table
        console.print(
            Panel(
                inner,
                title=f"[bold]  Справка: {q} [/bold]",
                border_style=_hp["accent"],
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        print(f"{CYAN}Справка (по запросу «{q}»):{RESET}")
        for _, cmds in filtered:
            for cmd, desc in cmds:
                clean = cmd.replace("[bright_green]", "").replace("[/bright_green]", "")
                print(f"  {CYAN}{clean:<22}{RESET} {desc}")
        if detail_lines:
            print()
            for ln in detail_lines:
                print(f"{DIM}{ln}{RESET}")
    print()


def print_commands() -> None:
    refresh_cli_ui_from_prefs()
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

        _cp = _cli_p()
        for cat_name, cmds in _HELP_CATEGORIES:
            table.add_row(f"\n[bold]{cat_name}[/bold]", "")
            for cmd, desc in cmds:
                table.add_row(f"  [cmd]{cmd}[/cmd]", desc)

        console.print(
            Panel(
                table,
                title="[bold]  Справка [/bold]",
                border_style=_cp["accent"],
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
        _th = _cli_p()
        console.print(
            Panel(
                Text(thought, style="italic cyan"),
                title="[bold cyan]🤔 Рассуждение[/bold cyan]",
                title_align="left",
                border_style=_th["accent"],
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


def print_deep_cli_session_banner(model: str, ctx_limit: int) -> None:
    """Rich-блок: что Deep Solver делает и что можно вводить (классический CLI)."""
    bridge = _get_tui_bridge()
    if bridge:
        return
    if not HAS_RICH:
        print()
        print("  [Deep Solver] Можно писать в чат — очередь сообщений. /stop — стоп.")
        return
    pal = _cli_p()
    body = (
        "[bold]Поле ввода внизу активно:[/bold] пиши уточнения и вопросы — они [cyan]встают в очередь[/cyan] и "
        "попадут в контекст на [cyan]следующем шаге[/cyan] (новый прогон не стартует).\n"
        f"[dim]Окно контекста ~{ctx_limit:,} ток. ·[/dim] [magenta]/stop[/magenta] [dim]— остановить Deep Solver.[/dim]\n"
        f"[dim]Сейчас · модель «{model}»[/dim]"
    )
    console.print(
        Panel(
            body,
            title="[bold]🧠 Deep Solver — что происходит[/bold]",
            title_align="left",
            border_style=pal["accent"],
            box=box.HEAVY,
            padding=(0, 1),
        )
    )


def print_deep_cli_heartbeat(
    *,
    elapsed: str,
    checkpoints: int,
    model: str,
    step_round: int,
    to_stderr: bool = False,
) -> None:
    """Компактная строка: время, чекпоинты, шаг (throttle снаружи).

    Для classic CLI ``to_stderr=True`` — не смешивать с stdout/prompt_toolkit.
    """
    bridge = _get_tui_bridge()
    if bridge:
        return
    line = (
        f"  [dim]⏱ {elapsed}[/dim]  ·  [magenta]чекпоинты {checkpoints}[/magenta]  ·  "
        f"[cyan]модель {model}[/cyan]  ·  [bold]шаг {step_round}[/bold]"
    )
    if not HAS_RICH:
        plain = f"  [Deep] шаг {step_round} · {elapsed} · чекпоинты {checkpoints} · {model}"
        print(plain, file=(sys.stderr if to_stderr else sys.stdout))
        return
    pal = _cli_p()
    out = _console_err if to_stderr and _console_err is not None else console
    out.print(
        line,
        style=pal.get("fg2", "dim"),
    )


def print_deep_cli_checkpoint(
    index: int, title: str, summary: str = "", cp_id: str = "",
) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        return
    if not HAS_RICH:
        print(f"  [cp #{index}] {title}")
        if summary:
            print(f"   {summary[:200]}")
        return
    pal = _cli_p()
    sub = f"[dim]{cp_id}[/dim]" if cp_id else ""
    body = (summary or "").strip() or "—"
    console.print(
        Panel(
            body,
            title=f"[bold]🧩 Чекпоинт #{index} · {title}[/bold]  {sub}",
            title_align="left",
            border_style=pal.get("green", "green"),
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def _get_tui_bridge():
    """Return the active TUI bridge, if any."""
    try:
        from Interface.tui_bridge import get_bridge
        return get_bridge()
    except Exception:
        return None


def print_info_block(
    lines: List[str] | str, title: str = "Инфо", *, accent: str = "dim",
) -> None:
    """Несколько строк в одной Rich-панели (команды /mode, /ollama, …)."""
    if isinstance(lines, str):
        body_lines = [lines] if lines else [""]
    else:
        body_lines = list(lines) if lines else [""]
    text_body = "\n".join(str(x) for x in body_lines)
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info(f"── {title} ──\n{text_body}")
        return
    if HAS_RICH:
        pal = _cli_p()
        bstyle = str(pal.get(accent) or pal.get("fg2") or "dim")
        console.print(
            Panel(
                Text(text_body, style=pal.get("fg2", "default"), no_wrap=False, overflow="fold"),
                title=f"[bold]{title}[/bold]",
                title_align="left",
                border_style=bstyle,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        print(f"  {CYAN}── {title} ──{RESET}")
        for line in body_lines:
            print(f"  {CYAN}{line}{RESET}")


def print_info(message: str) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_info(message)
        return
    if HAS_RICH:
        pal = _cli_p()
        console.print(
            Panel(
                Text(str(message), style=pal.get("fg2", "default"), overflow="fold"),
                title="[dim bold]ℹ Инфо[/dim bold]",
                title_align="left",
                border_style=str(pal.get("fg2", "dim")),
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        print(f"  {CYAN}{message}{RESET}")


def print_success(message: str) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_success(message)
        return
    if HAS_RICH:
        pal = _cli_p()
        console.print(
            Panel(
                Text(str(message), style=pal.get("green", "green"), overflow="fold"),
                title="[bold green]✓ Готово[/bold green]",
                title_align="left",
                border_style=str(pal.get("green", "green")),
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        print(f"  {GREEN}✓ {message}{RESET}")


def print_warning(message: str) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_warning(message)
        return
    if HAS_RICH:
        from rich.panel import Panel as RPanel
        from rich.text import Text
        from rich import box as rbox

        pal = _cli_p()
        console.print(
            RPanel(
                Text(str(message), style=f"bold {pal['yellow']}"),
                title="[bold]Предупреждение[/bold]",
                title_align="left",
                border_style=pal["yellow"],
                box=rbox.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        print(f"  {YELLOW}⚠ {message}{RESET}")


def print_error(message: str) -> None:
    bridge = _get_tui_bridge()
    if bridge:
        bridge.on_error(message)
        return
    if HAS_RICH:
        pal = _cli_p()
        console.print(
            Panel(
                Text(str(message), style=str(pal.get("red", "red")), overflow="fold"),
                title="[bold red]✗ Ошибка[/bold red]",
                title_align="left",
                border_style=str(pal.get("red", "red")),
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        print(f"  {RED}✗ {message}{RESET}")


def get_user_input() -> str:
    try:
        from Interface.ui_prefs import cli_prompt_prefix_plain

        pfx = cli_prompt_prefix_plain().rstrip() or "❯"
    except Exception:
        pfx = "❯"
    if HAS_RICH:
        try:
            return console.input(f"[bold cyan]{pfx}[/bold cyan] ")
        except (KeyboardInterrupt, EOFError):
            return "/exit"
    else:
        try:
            return input(f"{BLUE}{pfx}{RESET} ")
        except (KeyboardInterrupt, EOFError):
            return "/exit"


def read_cli_line(prompt: Optional[str] = None) -> str:
    """Одна строка ввода; при EOF/Ctrl+D — пустая строка (не ``/exit``), чтобы не путать с id модели."""
    if prompt is None:
        try:
            from Interface.ui_prefs import cli_prompt_prefix_plain

            prompt = cli_prompt_prefix_plain()
        except Exception:
            prompt = "❯ "
    if HAS_RICH:
        try:
            return (console.input(f"[bold cyan]{prompt}[/bold cyan]") or "").strip()
        except (KeyboardInterrupt, EOFError):
            return ""
    try:
        return (input(f"{BLUE}{prompt}{RESET}") or "").strip()
    except (KeyboardInterrupt, EOFError):
        return ""


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
        _rg = _cli_p()
        table = Table(
            title=f"[bold]RAG: '{query_text}'[/bold]",
            box=box.ROUNDED, padding=(0, 1), border_style=_rg["accent"],
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
    research_active: bool = False,
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
        if research_active:
            bridge.on_info("Research Mode: активен")
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
        if research_active:
            print(f"  Research Mode: активен")
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
    _esp = _cli_p()

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
    if research_active:
        content += "\n  [dim]Research Mode:[/dim] [bold cyan]активен[/bold cyan]"

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
            border_style=_esp["accent"],
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
        "/mode", "/normal", "/agentmode", "/deepmode", "/deep", "/creatormode", "/researchmode",
        "/research", "/ollama", "/deepcp", "/stop",
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
