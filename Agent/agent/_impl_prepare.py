"""Агент Lorne: основной цикл (TUI и classic), LangGraph, сессии, откаты, режимы."""
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

from Agent.runtime_paths import env_pref

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
    from .checkpoint import (
        create_session,
        delete_session,
        list_sessions,
        load_state,
        save_state,
        save_pre_turn_snapshot,
        load_pre_turn_snapshot,
        delete_turn_snapshots_from,
        save_pre_turn_workspace_snapshot,
        restore_turn_workspace,
        delete_turn_workspace_snapshots_from,
        messages_from_stored_dicts,
    )
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
    from Agent.checkpoint import (
        create_session,
        delete_session,
        list_sessions,
        load_state,
        save_state,
        save_pre_turn_snapshot,
        load_pre_turn_snapshot,
        delete_turn_snapshots_from,
        save_pre_turn_workspace_snapshot,
        restore_turn_workspace,
        delete_turn_workspace_snapshots_from,
        messages_from_stored_dicts,
    )
    from Agent.graph_runner import AgentGraph
    from Agent.message_utils import sanitize_messages, compact_conversation
    from Agent.spinner import LiveSpinner
    from Agent.command_router import CommandRouter, _should_autoplan

try:
    from Agent.creator_mode import run_creator_mode
except ImportError:
    from creator_mode import run_creator_mode

try:
    from .creator_summary import format_creator_summary_text
except ImportError:
    from Agent.creator_summary import format_creator_summary_text

try:
    from .creator_provider import get_creator_config, save_creator_config, check_local_server
except ImportError:
    from Agent.creator_provider import get_creator_config, save_creator_config, check_local_server

try:
    from .llm_provider import (
        get_llm, get_available_profiles, normalize_profile,
        get_available_models, set_model, get_saved_model,
        fetch_openrouter_credits, format_credits_info,
        unload_ollama_models,
        is_reasoning_model,
    )
except ImportError:
    from Agent.llm_provider import (
        get_llm, get_available_profiles, normalize_profile,
        get_available_models, set_model, get_saved_model,
        fetch_openrouter_credits, format_credits_info,
        unload_ollama_models,
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
        print_welcome, print_startup_banner, print_commands, print_session_list,
        print_thinking, print_planning, print_info, print_success,
        print_warning, print_error, get_user_input,
        print_deep_cli_session_banner, print_deep_cli_heartbeat, print_deep_cli_checkpoint,
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
    def print_welcome(m, p, n, b=""): print(f"Lorne — {m}" + (f" | {b}" if b else ""))
    def print_startup_banner(m, p, n, b="", **kw): print_welcome(m, p, n, b)
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
    def print_deep_cli_session_banner(m, c): pass
    def print_deep_cli_heartbeat(**kw): pass
    def print_deep_cli_checkpoint(*_a, **_k): pass
    console = None
    HAS_RICH = False

load_dotenv()

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


def _sync_tui_tool_bundle(mode_lower: str) -> None:
    """Rebuild global ``tools`` from TUI mode (Ask strips write tools; Creator/Deep/Research may add browser)."""
    global tools
    ml = (mode_lower or "agent").lower()
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
        fresh, _cust = build_tools(
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

# ─── Project analysis ──────────────────────────────────────────────
_SKIP_DIRS = {
    ".git", ".idea", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", ".cache", ".ruff_cache", "target", "out",
    "coverage", ".turbo", ".parcel-cache",
}

# Prompt-overhead budget for the project tree: keep the system message
# lean so we don't burn ~1.2k tokens per LLM call on a file listing that
# the model can always refetch via list_files.
_PROJECT_MAX_CHARS = 1800
_PROJECT_MAX_DEPTH = 2
_PROJECT_MAX_ENTRIES_PER_DIR = 25


def analyze_project_structure(
    root_path: Optional[Path] = None,
    *,
    max_chars: int = _PROJECT_MAX_CHARS,
    max_depth: int = _PROJECT_MAX_DEPTH,
    max_entries_per_dir: int = _PROJECT_MAX_ENTRIES_PER_DIR,
) -> str:
    """Build a compact tree of the project for the system prompt.

    Designed to stay under ~600 tokens: depth-limited, no per-file sizes,
    truncation of oversized directories and a hard character cap at the
    end. The model can always recover detail via `list_files`/`read_file`.
    """
    if root_path is None:
        root_path = Path.cwd()

    lines = [f"Project: {root_path.name}", f"Root: {root_path}", ""]
    file_types: Dict[str, int] = {}
    total_files = 0
    total_dirs = 0

    def _tree(directory: Path, prefix: str = "", depth: int = 0):
        nonlocal total_files, total_dirs
        if depth > max_depth:
            return
        try:
            items = sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return

        visible = [i for i in items if i.name not in _SKIP_DIRS and not i.name.startswith(".")]
        shown = visible[:max_entries_per_dir]
        hidden = len(visible) - len(shown)
        for idx, item in enumerate(shown):
            is_last = idx == len(shown) - 1 and hidden == 0
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "
            try:
                if item.is_dir():
                    total_dirs += 1
                    lines.append(f"{prefix}{connector}{item.name}/")
                    if depth < max_depth:
                        try:
                            _tree(item, prefix + extension, depth + 1)
                        except OSError:
                            lines.append(f"{prefix}{extension}    … (каталог недоступен)")
                else:
                    try:
                        item.stat()
                    except OSError:
                        lines.append(f"{prefix}{connector}{item.name} (недоступно)")
                        continue
                    total_files += 1
                    suffix = item.suffix or "(no ext)"
                    file_types[suffix] = file_types.get(suffix, 0) + 1
                    # no sizes — saves ~400 tok per turn, and sizes add no
                    # signal the agent actually acts on.
                    lines.append(f"{prefix}{connector}{item.name}")
            except OSError:
                lines.append(f"{prefix}{connector}{item.name} (недоступно)")
        if hidden > 0:
            lines.append(f"{prefix}└── … ({hidden} ещё — используй list_files)")

    _tree(root_path)

    lines.append(f"\nStats: {total_files} files, {total_dirs} directories")
    if file_types:
        top_types = sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:6]
        lines.append("Types: " + ", ".join(f"{ext}: {cnt}" for ext, cnt in top_types))

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 80].rstrip() + (
            "\n… [обрезано для экономии контекста — используй list_files для подробностей]"
        )
    return text


def _build_session_system_prompt(
    base_prompt: str,
    custom_tools_section: str,
    project_structure: str,
) -> str:
    """Assemble the system message shown once per session.

    Kept in a helper so the three call sites stay in sync — and the format
    stays compact (no duplicated tool-name list, no verbose session blurb).
    """
    sections = [base_prompt.rstrip()]
    ct = (custom_tools_section or "").strip()
    if ct:
        sections.append(ct)
    ps = (project_structure or "").strip()
    if ps:
        sections.append("=== КОНТЕКСТ ПРОЕКТА ===\n" + ps)
    sections.append(
        "=== СЕССИЯ ===\n"
        "Состояние сохраняется между запусками (SQLite checkpoint). "
        "Для поиска по документам — rag_search (сначала Project Brain, затем код)."
    )
    try:
        from Agent.prompts.project_brain_rules import PROJECT_BRAIN_SYSTEM_SECTION

        sections.append(PROJECT_BRAIN_SYSTEM_SECTION.strip())
    except Exception:
        pass
    return "\n\n".join(sections) + "\n"


# ─── LLM init ──────────────────────────────────────────────────────
MODEL_PROFILE = normalize_profile(env_pref("PROFILE", "balanced"))
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

def _print_creator_details(creator_result: dict, *, worker_panels: bool = True) -> None:
    """Rich/plain: опционально панели по воркерам; всегда — список недавно изменённых файлов."""
    if not creator_result or not creator_result.get("results"):
        return

    if worker_panels:
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
        else:
            print("\nДетальные отчеты агентов:")
            for r in creator_result.get("results", []):
                icon = "✓" if r["status"] == "done" else "✗"
                print(f"\n{icon} {r.get('worker_id', 'Unknown')} - {r.get('task', '')[:60]}")
                print("-" * 40)
                print(r.get("result", "Нет данных"))
                print("-" * 40)

    t_start = time.time() - creator_result.get("elapsed", 0)
    modified_files: List[str] = []
    try:
        for p in Path.cwd().rglob("*"):
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                if p.stat().st_mtime > t_start:
                    try:
                        modified_files.append(str(p.relative_to(Path.cwd())))
                    except ValueError:
                        pass
    except Exception:
        pass

    if modified_files:
        if HAS_RICH and console:
            console.print("\n[bold green]Измененные файлы:[/bold green]")
            for f in sorted(modified_files):
                console.print(f"  [dim]-[/dim] {f}")
        else:
            print("\nИзмененные файлы:")
            for f in sorted(modified_files):
                print(f"  - {f}")


# ─── Main loop ──────────────────────────────────────────────────────
