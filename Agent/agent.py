"""
TCA Agent — Terminal Coding Assistant.
LangGraph-based agent loop with beautiful terminal output, conversation compaction,
error recovery, and Claude Code-inspired UX.
"""
import json
import os
import re as _re
import sys
import time
import threading
from dotenv import load_dotenv
from pathlib import Path
from typing import Any, Dict, List, Optional
from json_repair import repair_json

_AGENT_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph, MessagesState
from langchain_core.tools import BaseTool

try:
    from .system_promt import SYSTEM_PROMPT
except ImportError:
    from system_promt import SYSTEM_PROMPT

try:
    from .path_utils import resolve_abs_path
except ImportError:
    def resolve_abs_path(path_str: str) -> Path:
        p = Path(path_str).expanduser()
        return (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()

try:
    from .tools import (
        read_file, list_files, edit_file, search_in_files, write_file,
        get_file_line_count, run_command, create_pdf, ask_user,
        create_code_file, append_code_snippet,
        save_plan, load_plan, update_plan, clear_plan,
        list_file_versions, rollback_file,
    )
    from .rag import index_documents, get_rag_tool
    from .checkpoint import create_session, delete_session, list_sessions, load_state, save_state
except ImportError:
    from Agent.tools import (
        read_file, list_files, edit_file, search_in_files, write_file,
        get_file_line_count, run_command, create_pdf, ask_user,
        create_code_file, append_code_snippet,
        save_plan, load_plan, update_plan, clear_plan,
        list_file_versions, rollback_file,
    )
    from Agent.rag import index_documents, get_rag_tool
    from Agent.checkpoint import create_session, delete_session, list_sessions, load_state, save_state

try:
    from .llm_provider import (
        get_llm, get_available_profiles, normalize_profile,
        AVAILABLE_MODELS, set_model, get_saved_model,
        fetch_openrouter_credits, format_credits_info,
        supports_parallel_tool_calls_param, is_reasoning_model,
    )
except ImportError:
    from Agent.llm_provider import (
        get_llm, get_available_profiles, normalize_profile,
        AVAILABLE_MODELS, set_model, get_saved_model,
        fetch_openrouter_credits, format_credits_info,
        supports_parallel_tool_calls_param, is_reasoning_model,
    )

try:
    from .planner import build_plan
except ImportError:
    from Agent.planner import build_plan

try:
    from Interface.visualization import (
        section, step, round_header,
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
    def step(n, title, detail=""): print(f"  Step {n}: {title}")
    def round_header(n): print(f"\n--- Round {n} ---")
    def display_agent_action(sn, name, args): step(sn, f"Tool: {name}")
    def display_tool_result(sn, name, result): step(sn, f"Result: {name}")
    def display_model_reply(sn, content, meta=None): print(content[:500] if content else "")
    def display_turn_summary(files): pass
    def display_usage(meta, limit=None, prefix="   "): return {}
    def display_cumulative_usage(cum, limit, name=""): pass
    def get_context_limit(name): return 128_000
    def print_welcome(m, p, n, b=""): print(f"TCA — {m}" + (f" | {b}" if b else ""))
    def print_commands(): print("  /help, /exit")
    def print_session_list(s): pass
    def print_thinking(): print("  Thinking…")
    def print_planning(t): print(f"  Planning: {t}")
    def print_info(m): print(f"  {m}")
    def print_success(m): print(f"  ✓ {m}")
    def print_warning(m): print(f"  ⚠ {m}")
    def print_error(m): print(f"  ✗ {m}")
    def get_user_input():
        try:
            return input("> ")
        except (KeyboardInterrupt, EOFError):
            return "/exit"
    console = None
    HAS_RICH = False

load_dotenv()

# ─── Tools ──────────────────────────────────────────────────────────
tools = [
    read_file, list_files, edit_file, write_file, get_file_line_count,
    create_code_file, append_code_snippet,
    save_plan, load_plan, update_plan, clear_plan,
    list_file_versions, rollback_file,
    search_in_files, run_command, create_pdf, ask_user,
    get_rag_tool(),
]

# ─── Project analysis ──────────────────────────────────────────────
_SKIP_DIRS = {".git", ".idea", "__pycache__", "node_modules", ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".next", ".nuxt"}

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
            if item.is_dir():
                total_dirs += 1
                lines.append(f"{prefix}{connector}{item.name}/")
                _tree(item, prefix + extension, depth + 1, max_depth)
            else:
                total_files += 1
                suffix = item.suffix or "(no ext)"
                file_types[suffix] = file_types.get(suffix, 0) + 1
                size_kb = item.stat().st_size / 1024
                size_str = f"{size_kb:.1f}KB" if size_kb >= 1 else f"{item.stat().st_size}B"
                lines.append(f"{prefix}{connector}{item.name} ({size_str})")

    _tree(root_path)

    lines.append(f"\nStats: {total_files} files, {total_dirs} directories")
    if file_types:
        top_types = sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:8]
        lines.append("Types: " + ", ".join(f"{ext}: {cnt}" for ext, cnt in top_types))

    return "\n".join(lines)


# ─── LLM init ──────────────────────────────────────────────────────
MODEL_PROFILE = normalize_profile(os.getenv("TCA_PROFILE", "balanced"))
MODEL_NAME = ""
CONTEXT_LIMIT = get_context_limit("meta-llama/llama-3.1-8b-instruct")
llm = None
llm_with_tools = None


_parallel_tools_disabled = False


def _bind_tools_safe(llm_obj: Any, model_name: str, force_no_parallel: bool = False) -> Any:
    """Bind tools respecting provider capabilities.
    Only passes parallel_tool_calls=False for providers known to support it
    (e.g. OpenAI). Other providers (Anthropic via Bedrock, Llama, etc.) may
    reject the extra key, so we omit it.
    """
    use_parallel_flag = (
        not force_no_parallel
        and supports_parallel_tool_calls_param(model_name)
    )
    try:
        if use_parallel_flag:
            return llm_obj.bind_tools(tools, parallel_tool_calls=False)
        return llm_obj.bind_tools(tools)
    except TypeError:
        return llm_obj.bind_tools(tools)


def _init_llm(profile: Optional[str] = None) -> None:
    global llm, llm_with_tools, MODEL_NAME, MODEL_PROFILE, CONTEXT_LIMIT, _parallel_tools_disabled
    if profile is None:
        profile = MODEL_PROFILE
    llm_obj, profile_name, model_name = get_llm(profile)
    MODEL_PROFILE = profile_name
    MODEL_NAME = model_name
    CONTEXT_LIMIT = get_context_limit(MODEL_NAME)
    _parallel_tools_disabled = False
    llm = llm_obj
    llm_with_tools = _bind_tools_safe(llm_obj, model_name)


_init_llm(MODEL_PROFILE)


# ─── Live spinner for LLM calls ─────────────────────────────────────
_spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

class _LiveSpinner:
    """Animated spinner that runs in a background thread during long operations."""
    def __init__(self, message: str = "Модель думает"):
        self._message = message
        self._running = False
        self._thread = None
        self._start_time = 0.0

    def start(self):
        self._running = True
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
        elapsed = time.time() - self._start_time
        # Clear spinner line
        sys.stdout.write(f"\r\033[K")
        sys.stdout.flush()
        if HAS_RICH and console:
            console.print(f"  [dim]✓ {self._message} ({elapsed:.1f}с)[/dim]")
        else:
            print(f"  ✓ {self._message} ({elapsed:.1f}с)")

    def _spin(self):
        idx = 0
        while self._running:
            elapsed = time.time() - self._start_time
            frame = _spinner_frames[idx % len(_spinner_frames)]
            if HAS_RICH:
                line = f"\r  \033[36m{frame}\033[0m \033[1m{self._message}\033[0m \033[2m({elapsed:.0f}с)\033[0m  "
            else:
                line = f"\r  {frame} {self._message} ({elapsed:.0f}с)  "
            sys.stdout.write(line)
            sys.stdout.flush()
            idx += 1
            time.sleep(0.1)


# ─── Helpers for provider-compatibility recovery ───────────────────

_RETRIABLE_PATTERNS = [
    "disable_parallel_tool_use",
    "parallel_tool_calls",
    "extraneous key",
]


def _is_retriable_bind_error(exc: Exception) -> bool:
    """Check if the error is caused by an unsupported bind_tools parameter."""
    msg = str(exc).lower()
    return any(p in msg for p in _RETRIABLE_PATTERNS)


def _strip_think_tags(text: str) -> str:
    """Remove <think>…</think> blocks emitted by reasoning models (DeepSeek R1, QwQ)."""
    return _re.sub(r"<think>[\s\S]*?</think>", "", text).strip()


# ─── Message sanitization ──────────────────────────────────────────

def _sanitize_messages(messages: List[Any]) -> List[Any]:
    """Fix message history to prevent API errors.

    Handles two classes of problems that cause 400 "No tool call found":
    1. Orphaned ToolMessages — their AIMessage was lost (e.g. compaction/restore)
    2. Dangling tool_calls — AIMessage has tool_calls but ToolMessages are missing
       (e.g. interrupted session, partial save)
    """
    declared_ids: set = set()
    answered_ids: set = set()

    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in (getattr(msg, "tool_calls", None) or []):
                tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                if tc_id:
                    declared_ids.add(tc_id)
        elif isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", "")
            if tc_id:
                answered_ids.add(tc_id)

    orphan_ids = answered_ids - declared_ids
    dangling_ids = declared_ids - answered_ids

    if not orphan_ids and not dangling_ids:
        return messages

    if orphan_ids:
        print_warning(f"Удалено {len(orphan_ids)} осиротевших результатов инструментов")
    if dangling_ids:
        print_warning(f"Исправлено {len(dangling_ids)} незавершённых вызовов инструментов")

    result: List[Any] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", "")
            if tc_id in orphan_ids:
                continue
            result.append(msg)
        elif isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            tc_ids: set = set()
            for tc in msg.tool_calls:
                tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                if tc_id:
                    tc_ids.add(tc_id)
            dangling_in_msg = tc_ids & dangling_ids
            if dangling_in_msg:
                if dangling_in_msg == tc_ids:
                    content = msg.content or "[Вызов инструментов был прерван]"
                    result.append(AIMessage(content=content))
                else:
                    result.append(msg)
                    for tc_id in dangling_in_msg:
                        result.append(ToolMessage(
                            content="[Операция была прервана]",
                            tool_call_id=tc_id,
                        ))
            else:
                result.append(msg)
        else:
            result.append(msg)

    return result


# ─── Transient error retry ─────────────────────────────────────────

_MAX_LLM_RETRIES = 2

_TRANSIENT_PATTERNS = [
    "provider returned error",
    "rate limit",
    "overloaded",
    "server error",
    "no tool call found",
    "trust-request-chat-template",
    "bad gateway",
    "service unavailable",
    "529",
    "internally_terminated",
]


def _is_transient_error(exc: Exception) -> bool:
    """Check if the error is a transient provider error that may resolve on retry."""
    msg = str(exc).lower()
    return any(p in msg for p in _TRANSIENT_PATTERNS)


# ─── LangGraph nodes ───────────────────────────────────────────────
def call_model(state: MessagesState) -> Dict[str, List[AIMessage]]:
    global llm_with_tools, _parallel_tools_disabled
    messages = _sanitize_messages(state["messages"])

    raw_response = None
    last_error = None

    for attempt in range(_MAX_LLM_RETRIES + 1):
        spinner = _LiveSpinner("Модель думает")
        spinner.start()
        try:
            raw_response = llm_with_tools.invoke(messages)
            spinner.stop()
            last_error = None
            break
        except Exception as e:
            spinner.stop()
            last_error = e

            if _is_retriable_bind_error(e) and not _parallel_tools_disabled:
                print_warning("Провайдер не поддерживает parallel_tool_calls — повторяю без него")
                _parallel_tools_disabled = True
                llm_with_tools = _bind_tools_safe(llm, MODEL_NAME, force_no_parallel=True)
                continue

            if _is_transient_error(e) and attempt < _MAX_LLM_RETRIES:
                wait = (attempt + 1) * 3
                print_warning(
                    f"Ошибка провайдера, повтор через {wait}с… "
                    f"({attempt + 1}/{_MAX_LLM_RETRIES})"
                )
                time.sleep(wait)
                continue

            break

    if last_error is not None:
        error_msg = f"Ошибка LLM: {type(last_error).__name__}: {last_error}"
        print_error(error_msg)
        return {"messages": [AIMessage(content=error_msg)]}

    content = raw_response.content or ""
    if isinstance(content, str):
        content = content.encode("utf-8", "ignore").decode("utf-8", "ignore")
        if is_reasoning_model(MODEL_NAME):
            content = _strip_think_tags(content)

    meta = getattr(raw_response, "response_metadata", None) or {}

    if getattr(raw_response, "tool_calls", None):
        return {"messages": [AIMessage(content=content or "", tool_calls=raw_response.tool_calls, response_metadata=meta)]}

    fixed_content = repair_json(content)
    if fixed_content.strip():
        try:
            parsed = json.loads(fixed_content)
            parsed_tools = [parsed] if not isinstance(parsed, list) else parsed
            tool_calls = []
            for t in parsed_tools:
                if not isinstance(t, dict) or "function" not in t:
                    continue
                func = t["function"]
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                elif not isinstance(args, dict):
                    args = {}
                tool_calls.append({
                    "name": func["name"],
                    "args": args,
                    "id": str(t.get("id", "call_" + str(hash(func["name"])))),
                    "type": "tool_call",
                })
            if tool_calls:
                return {"messages": [AIMessage(content="", tool_calls=tool_calls, response_metadata=meta)]}
        except json.JSONDecodeError:
            pass

    return {"messages": [AIMessage(content=content, response_metadata=meta)]}


_TOOL_MAP: Dict[str, BaseTool] = {}
for _t in tools:
    name = getattr(_t, "name", None) or getattr(_t, "__name__", None)
    if name:
        _TOOL_MAP[str(name)] = _t


def _normalize_tool_call(tc: Any) -> Dict[str, Any]:
    if isinstance(tc, dict):
        return {"name": tc.get("name") or tc.get("tool") or "", "args": tc.get("args") or {}, "id": tc.get("id") or ""}
    return {"name": getattr(tc, "name", "") or "", "args": getattr(tc, "args", {}) or {}, "id": getattr(tc, "id", "") or ""}


_CONTENT_FIELD_MAP = {
    "write_file": ("content", {"path"}),
    "create_code_file": ("code", {"filepath", "language"}),
    "append_code_snippet": ("snippet", {"filepath", "language"}),
}


def _reconstruct_broken_content(tool_name: str, args: dict) -> dict:
    """Fix broken tool call args where the LLM failed to JSON-escape multi-line code.

    Small models often break at inner quotes: the content string gets terminated
    early and subsequent code fragments become spurious JSON keys/values.
    Pattern: {"path":"x.py","content":"def f():\\n    print(\\"","Hello":"\\")\\n..."}
    We detect extra unexpected keys and concatenate everything back into the
    content field.
    """
    if tool_name not in _CONTENT_FIELD_MAP:
        return args

    content_key, known_keys = _CONTENT_FIELD_MAP[tool_name]
    all_known = known_keys | {content_key}
    extra_keys = [k for k in args if k not in all_known]

    if not extra_keys:
        return args

    def _flatten(v: Any) -> str:
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            parts: List[str] = []
            for dk, dv in v.items():
                parts.append(dk)
                parts.append(_flatten(dv))
            return "".join(parts)
        return str(v)

    parts = [str(args.get(content_key, ""))]
    for k in extra_keys:
        parts.append(k)
        parts.append(_flatten(args[k]))

    new_args = {k: args[k] for k in all_known if k in args}
    new_args[content_key] = "".join(parts)

    print_warning(
        f"Восстановлен сломанный JSON для {tool_name}: "
        f"контент был разбит на {len(extra_keys) + 1} фрагментов, склеен обратно "
        f"({len(new_args[content_key])} симв.)"
    )
    return new_args


# ─── Token-saving: truncate large tool results ─────────────────────
_TOOL_RESULT_LIMITS: Dict[str, int] = {
    "read_file": 4000,
    "search_in_files": 3000,
    "run_command": 3000,
    "list_files": 2000,
    "rag_search": 3000,
}
_DEFAULT_RESULT_LIMIT = 3000


def _truncate_result(tool_name: str, content_str: str) -> str:
    """Truncate tool result content to save context tokens.
    The full output is already displayed in the terminal — the model only
    needs enough to make decisions.
    """
    limit = _TOOL_RESULT_LIMITS.get(tool_name, _DEFAULT_RESULT_LIMIT)
    if len(content_str) <= limit:
        return content_str
    half = limit // 2
    return (
        content_str[:half]
        + f"\n\n… [{len(content_str) - limit} символов пропущено для экономии контекста] …\n\n"
        + content_str[-half:]
    )


def _annotate_errors(tool_name: str, result: Any) -> str:
    """Add explicit error prefix to tool results so the model cannot ignore failures."""
    try:
        content_str = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        content_str = str(result)

    if not isinstance(result, dict):
        return _truncate_result(tool_name, content_str)

    has_error = False
    error_detail = ""

    if result.get("error"):
        has_error = True
        error_detail = str(result.get("detail") or result.get("error"))
    elif result.get("returncode") and int(result.get("returncode", 0)) != 0:
        has_error = True
        stderr = result.get("stderr", "")
        error_detail = stderr[:300] if stderr else f"returncode={result['returncode']}"
    elif result.get("skipped"):
        has_error = True
        error_detail = result.get("reason", "skipped")

    if has_error:
        content_str = (
            f"⚠ ОШИБКА при выполнении {tool_name}: {error_detail}\n"
            f"НЕ отмечай этот шаг как completed. Исправь проблему или попробуй другой подход.\n"
            f"Полный результат: {content_str}"
        )

    return _truncate_result(tool_name, content_str)


def execute_tools(state: MessagesState) -> Dict[str, List[Any]]:
    """Execute ALL tool calls from the last AIMessage sequentially."""
    messages = state["messages"]
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return {"messages": []}

    results: List[Any] = []
    for tc in tool_calls:
        tc_norm = _normalize_tool_call(tc)
        tool_name = str(tc_norm.get("name") or "")
        tool_args = tc_norm.get("args") or {}
        tool_call_id = str(tc_norm.get("id") or f"call_{hash(tool_name)}_{len(results)}")

        tool_args = _reconstruct_broken_content(tool_name, tool_args)

        display_agent_action(len(results) + 1, tool_name, tool_args)

        tool = _TOOL_MAP.get(tool_name)
        if tool is None:
            result = {"error": "unknown_tool", "tool": tool_name, "available": list(_TOOL_MAP.keys())}
        else:
            try:
                result = tool.invoke(tool_args)
            except Exception as e:
                result = {"error": type(e).__name__, "detail": str(e)}

        parsed = result if isinstance(result, (dict, list)) else str(result)
        display_tool_result(len(results) + 1, tool_name, parsed)

        content_str = _annotate_errors(tool_name, result)
        results.append(ToolMessage(content=content_str, tool_call_id=tool_call_id, name=tool_name))

    return {"messages": results}


def should_continue(state: MessagesState) -> str:
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END


workflow = StateGraph(state_schema=MessagesState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", execute_tools)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
workflow.add_edge("tools", "agent")
app = workflow.compile()


# ─── Conversation compaction ────────────────────────────────────────
def compact_conversation(messages: List[Any], keep_last: int = 10) -> List[Any]:
    """Summarize old messages to free up context window.
    Keeps the system message, compacts old exchanges into a summary, keeps recent messages."""
    if len(messages) <= keep_last + 5:
        return messages

    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(non_system) <= keep_last:
        return messages

    split_idx = len(non_system) - keep_last

    # Don't orphan ToolMessages: walk backwards to include the AIMessage
    # that generated them, keeping the tool call group intact.
    while split_idx > 0 and isinstance(non_system[split_idx], ToolMessage):
        split_idx -= 1

    if split_idx <= 0:
        return messages

    old_msgs = non_system[:split_idx]
    recent_msgs = non_system[split_idx:]

    summary_parts = []
    for msg in old_msgs:
        if isinstance(msg, HumanMessage):
            text = (msg.content or "").strip()
            if text:
                summary_parts.append(f"User: {text[:200]}")
        elif isinstance(msg, AIMessage):
            text = (msg.content or "").strip()
            if text:
                summary_parts.append(f"Assistant: {text[:200]}")
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    n = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                    summary_parts.append(f"  [tool call: {n}]")
        elif isinstance(msg, ToolMessage):
            n = getattr(msg, "name", "tool")
            summary_parts.append(f"  [tool result: {n}]")

    summary_text = (
        "=== CONVERSATION HISTORY (compacted) ===\n"
        "The following is a summary of earlier conversation:\n\n"
        + "\n".join(summary_parts[-40:])
        + "\n\n=== END OF HISTORY ===\n"
        "Continue the conversation from here."
    )

    compacted = system_msgs + [HumanMessage(content=summary_text)] + recent_msgs
    return compacted


# ─── Main loop ──────────────────────────────────────────────────────
def run_coding_agent_loop():
    print_info("Анализирую структуру проекта…")
    project_structure = analyze_project_structure()

    enhanced_system_prompt = f"""{SYSTEM_PROMPT}

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
    sessions = list_sessions(limit=12)
    if sessions:
        print_session_list(sessions)

    print_info("Выбери сессию: Enter=новая | номер/ID=продолжить | d номер/ID=удалить")
    try:
        choice = get_user_input().strip()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    session_id = ""
    messages: List[Any] = []

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
                messages = _sanitize_messages(
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

    # RAG indexing
    try:
        n_rag = index_documents(str(Path.cwd()), pattern="*.py")
        print_info(f"RAG: проиндексировано {n_rag} Python файлов")
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
            for state in app.stream({"messages": messages}, stream_mode="values"):
                messages = state["messages"]
                chunk = messages[printed_len:]
                if not chunk:
                    continue
                for msg in chunk:
                    if isinstance(msg, AIMessage):
                        if msg.tool_calls:
                            # Show round header; tool calls + results are displayed
                            # by execute_tools in real-time during execution
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
                        # Track file changes for turn summary
                        # (display already done by execute_tools)
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

    # ─── Main input loop ────────────────────────────────────────
    while True:
        user_input = get_user_input().strip()
        low = user_input.lower()

        if low in ("/exit", "exit", "quit", "q"):
            print_info("До встречи!")
            break

        if low in ("/help", "help"):
            print_commands()
            continue

        if low.startswith("/ls"):
            parts = user_input.split(maxsplit=1)
            p = parts[1].strip() if len(parts) > 1 else "."
            try:
                listing = list_files.invoke({"path": p, "recursive": False, "pattern": "*"})
                entries = listing.get("entries", []) if isinstance(listing, dict) else []
                display_tool_result(0, "list_files", listing)
            except Exception as e:
                print_error(f"/ls: {e}")
            continue

        if low.startswith("/tree"):
            parts = user_input.split(maxsplit=1)
            p = parts[1].strip() if len(parts) > 1 else "."
            try:
                root = resolve_abs_path(p)
                tree = analyze_project_structure(root)
                if HAS_RICH and console:
                    from rich.panel import Panel
                    from rich import box as rbox
                    console.print(Panel(tree, title="Project Tree", border_style="cyan", box=rbox.ROUNDED))
                else:
                    print(tree)
            except Exception as e:
                print_error(f"/tree: {e}")
            continue

        if low.startswith("/plan"):
            messages.append(HumanMessage(content="Show the current plan using load_plan()."))
            old_len = len(messages)
            _run_and_render(old_len)
            continue

        if low.startswith("/status"):
            human_count = len([m for m in messages if isinstance(m, HumanMessage)])
            ai_count = len([m for m in messages if isinstance(m, AIMessage)])
            tool_count = len([m for m in messages if isinstance(m, ToolMessage)])
            print_info(f"Профиль: {MODEL_PROFILE} | Модель: {MODEL_NAME}")
            print_info(f"Лимит контекста: {CONTEXT_LIMIT:,} токенов")
            print_info(f"Сообщения: {human_count} пользователь, {ai_count} ассистент, {tool_count} инструменты")
            print_info(f"Всего сообщений: {len(messages)}")
            continue

        if low.startswith("/profile"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1:
                print_info(f"Текущий: {MODEL_PROFILE} ({MODEL_NAME})")
                print_info(f"Доступные: {', '.join(sorted(get_available_profiles().keys()))}")
                continue
            new_profile = parts[1].strip()
            _init_llm(new_profile)
            print_success(f"Переключено на: {MODEL_PROFILE} ({MODEL_NAME})")
            continue

        if low.startswith("/model"):
            parts = user_input.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                custom_model = parts[1].strip()
                set_model(custom_model)
                _init_llm()
                print_success(f"Модель установлена: {MODEL_NAME}")
                print_info("Выбор сохранён и будет использоваться при следующем запуске")
                continue
            if HAS_RICH and console:
                from rich.table import Table as RTable
                from rich import box as rbox
                tbl = RTable(
                    title="[bold]Доступные модели[/bold]",
                    box=rbox.SIMPLE,
                    padding=(0, 1),
                )
                tbl.add_column("#", style="bold", width=3)
                tbl.add_column("Модель", style="cyan")
                tbl.add_column("ID", style="dim")
                tbl.add_column("Контекст", justify="right")
                tbl.add_column("Тип", style="dim")
                for i, m in enumerate(AVAILABLE_MODELS, 1):
                    ctx = f"{m['ctx']:,}"
                    current = " ◀" if m["id"] == MODEL_NAME else ""
                    tbl.add_row(str(i), m["name"] + current, m["id"], ctx, m["tier"])
                console.print(tbl)
            else:
                print_info("Доступные модели:")
                for i, m in enumerate(AVAILABLE_MODELS, 1):
                    cur = " ◀ текущая" if m["id"] == MODEL_NAME else ""
                    print(f"  {i:>2}. {m['name']:<25} {m['id']:<45} {m['tier']}{cur}")
            print_info("Введи номер модели, или /model <model_id> для произвольной модели:")
            try:
                choice = get_user_input().strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not choice:
                continue
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(AVAILABLE_MODELS):
                    chosen = AVAILABLE_MODELS[idx]["id"]
                    set_model(chosen)
                    _init_llm()
                    print_success(f"Модель: {MODEL_NAME}")
                    print_info("Выбор сохранён")
                else:
                    print_error(f"Неверный номер. Введи 1-{len(AVAILABLE_MODELS)}")
            else:
                set_model(choice)
                _init_llm()
                print_success(f"Модель: {MODEL_NAME}")
                print_info("Выбор сохранён")
            continue

        if low.startswith("/balance") or low.startswith("/credits"):
            print_info("Запрос баланса OpenRouter…")
            creds = fetch_openrouter_credits()
            if creds is None:
                print_error("Не удалось получить данные. Проверь OPENROUTER_API_KEY.")
            else:
                info = format_credits_info(creds)
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
            continue

        if low.startswith("/compact"):
            before = len(messages)
            messages = compact_conversation(messages, keep_last=12)
            after = len(messages)
            if before != after:
                print_success(f"Сжато: {before} → {after} сообщений")
                try:
                    save_state(messages, session_id=session_id)
                except Exception:
                    pass
            else:
                print_info("Разговор уже компактный")
            continue

        if low.startswith("/versions"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print_warning("Использование: /versions <путь>")
                continue
            p = parts[1].strip()
            messages.append(HumanMessage(content=f"Show file versions using list_file_versions(path='{p}')."))
            old_len = len(messages)
            _run_and_render(old_len)
            continue

        if low.startswith("/rollback"):
            parts = user_input.split()
            if len(parts) < 2:
                print_warning("Использование: /rollback <путь> [version_id]")
                continue
            p = parts[1].strip()
            vid = parts[2].strip() if len(parts) >= 3 else ""
            messages.append(HumanMessage(content=f"Rollback file using rollback_file(path='{p}', version_id='{vid}')."))
            old_len = len(messages)
            _run_and_render(old_len)
            continue

        if low.startswith("/agent"):
            from Agent.multiagent import list_agents, set_current_agent
            parts = user_input.split()
            if len(parts) == 1 or parts[1] == "list":
                print_info("Под-агенты:")
                for a in list_agents():
                    print_info(f"  - {a.get('id')}: {a.get('title')}")
                continue
            if parts[1] == "use" and len(parts) >= 3:
                aid = set_current_agent(parts[2])
                print_success(f"Текущий под-агент: {aid}")
                continue
            print_warning("Использование: /agent list | /agent use <id>")
            continue

        # Auto-compact if approaching context limit
        non_system_count = len([m for m in messages if not isinstance(m, SystemMessage)])
        if non_system_count > 30:
            messages = compact_conversation(messages, keep_last=10)
            print_info("Авто-сжатие разговора для освобождения контекста")

        if not user_input:
            messages.append(HumanMessage(content="Продолжи, сделай следующий шаг если нужно."))
        else:
            if _should_autoplan(user_input):
                print_planning(user_input)
                plan_spinner = _LiveSpinner("Составляю план")
                plan_spinner.start()
                try:
                    steps = build_plan(user_input)
                    plan_spinner.stop()
                    if steps:
                        try:
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


if __name__ == "__main__":
    run_coding_agent_loop()
