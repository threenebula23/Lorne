"""Message sanitization, compaction, and tool result processing utilities."""
import json
import re as _re
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

try:
    from Interface.visualization import print_warning
except ImportError:
    def print_warning(m):
        print(f"  ⚠ {m}")


# ─── Provider-compatibility helpers ─────────────────────────────────

_RETRIABLE_PATTERNS = [
    "disable_parallel_tool_use",
    "parallel_tool_calls",
    "extraneous key",
]


def is_retriable_bind_error(exc: Exception) -> bool:
    """Check if the error is caused by an unsupported bind_tools parameter."""
    msg = str(exc).lower()
    return any(p in msg for p in _RETRIABLE_PATTERNS)


def strip_think_tags(text: str) -> str:
    """Remove <think>…</think> blocks emitted by reasoning models."""
    return _re.sub(r"<think>[\s\S]*?</think>", "", text).strip()


# ─── Transient error retry ──────────────────────────────────────────

MAX_LLM_RETRIES = 2

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


def is_transient_error(exc: Exception) -> bool:
    """Check if the error is a transient provider error that may resolve on retry."""
    msg = str(exc).lower()
    return any(p in msg for p in _TRANSIENT_PATTERNS)


# ─── Message sanitization ──────────────────────────────────────────

def sanitize_messages(messages: List[Any]) -> List[Any]:
    """Fix message history to prevent API errors.

    Handles two classes of problems that cause 400 "No tool call found":
    1. Orphaned ToolMessages — their AIMessage was lost (e.g. compaction/restore)
    2. Dangling tool_calls — AIMessage has tool_calls but ToolMessages are missing
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


# ─── Tool call normalization ────────────────────────────────────────

def normalize_tool_call(tc: Any) -> Dict[str, Any]:
    if isinstance(tc, dict):
        return {
            "name": tc.get("name") or tc.get("tool") or "",
            "args": tc.get("args") or {},
            "id": tc.get("id") or "",
        }
    return {
        "name": getattr(tc, "name", "") or "",
        "args": getattr(tc, "args", {}) or {},
        "id": getattr(tc, "id", "") or "",
    }


# ─── Broken JSON reconstruction ────────────────────────────────────

_CONTENT_FIELD_MAP = {
    "write_file": ("content", {"path"}),
    "create_code_file": ("code", {"filepath", "language"}),
    "append_code_snippet": ("snippet", {"filepath", "language"}),
}


def reconstruct_broken_content(tool_name: str, args: dict) -> dict:
    """Fix broken tool call args where the LLM failed to JSON-escape multi-line code."""
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

TOOL_RESULT_LIMITS: Dict[str, int] = {
    "read_file": 4000,
    "search_in_files": 3000,
    "run_command": 3000,
    "list_files": 2000,
    "rag_search": 3000,
    "web_search": 9000,
    "web_fetch": 14_000,
    "web_search_and_read": 14_000,
    "ocr_read_file_soft": 7000,
    "ocr_read_image_medium": 7000,
    "ocr_read_photo_strong": 9000,
    "office_document_read": 10_000,
    "docx_document_create": 4000,
    "docx_document_append_paragraphs": 4000,
    "docx_document_patch_paragraphs": 4000,
    "pdf_styled_document_create": 4000,
}
DEFAULT_RESULT_LIMIT = 3000

_WEB_COMPACT_TOOLS = frozenset({"web_search", "web_fetch", "web_search_and_read"})
_OCR_COMPACT_TOOLS = frozenset({
    "ocr_read_file_soft", "ocr_read_image_medium", "ocr_read_photo_strong",
})
_OFFICE_COMPACT_TOOLS = frozenset({"office_document_read"})


def truncate_result(tool_name: str, content_str: str) -> str:
    """Truncate tool result content to save context tokens."""
    limit = TOOL_RESULT_LIMITS.get(tool_name, DEFAULT_RESULT_LIMIT)
    if len(content_str) <= limit:
        return content_str
    half = limit // 2
    return (
        content_str[:half]
        + f"\n\n… [{len(content_str) - limit} символов пропущено для экономии контекста] …\n\n"
        + content_str[-half:]
    )


def annotate_errors(tool_name: str, result: Any) -> str:
    """Add explicit error prefix to tool results so the model cannot ignore failures."""
    try:
        content_str = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        content_str = str(result)

    if not isinstance(result, dict):
        return truncate_result(tool_name, content_str)

    def _tool_failed(d: dict) -> bool:
        if d.get("error"):
            return True
        try:
            rc = d.get("returncode")
            if rc is not None and int(rc) != 0:
                return True
        except (TypeError, ValueError):
            pass
        if d.get("skipped"):
            return True
        return False

    if (
        tool_name in _WEB_COMPACT_TOOLS
        and not _tool_failed(result)
        and result.get("_model_compact")
    ):
        return truncate_result(tool_name, str(result["_model_compact"]))

    if (
        tool_name in _OCR_COMPACT_TOOLS
        and not _tool_failed(result)
        and result.get("_model_compact")
    ):
        return truncate_result(tool_name, str(result["_model_compact"]))

    if (
        tool_name in _OFFICE_COMPACT_TOOLS
        and not _tool_failed(result)
        and result.get("_model_compact")
    ):
        return truncate_result(tool_name, str(result["_model_compact"]))

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

    return truncate_result(tool_name, content_str)


# ─── Conversation compaction ────────────────────────────────────────

def compact_conversation(messages: List[Any], keep_last: int = 10) -> List[Any]:
    """Summarize old messages to free up context window."""
    if len(messages) <= keep_last + 5:
        return messages

    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(non_system) <= keep_last:
        return messages

    split_idx = len(non_system) - keep_last

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
