"""Message sanitization, compaction, and tool result processing utilities."""
import ast
import json
import re as _re
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
try:
    from json_repair import repair_json
except Exception:
    def repair_json(text: str) -> str:
        return str(text or "")

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
    """Remove <think>…</think>, Qwen <think>…</think>, and <thought> blocks."""
    out = str(text or "")
    out = _re.sub(r"<redacted_thinking>[\s\S]*?</redacted_thinking>", "", out, flags=_re.IGNORECASE)
    out = _re.sub(r"<thinking>[\s\S]*?</thinking>", "", out, flags=_re.IGNORECASE)
    out = _re.sub(r"<think>[\s\S]*?</think>", "", out, flags=_re.IGNORECASE)
    out = _re.sub(r"<thought>[\s\S]*?</thought>", "", out, flags=_re.IGNORECASE)
    # Some local models stop mid-response and leave an opening tag without a closer.
    out = _re.sub(r"<(?:redacted_thinking|thinking|think|thought)>[\s\S]*$", "", out, flags=_re.IGNORECASE)
    return out.strip()


def extract_thought_segments(text: str) -> tuple[List[str], str]:
    """Extract reasoning blocks for UI: <thought>, <think>, Qwen <think>."""
    if not (text or "").strip():
        return [], text or ""
    thoughts: List[str] = []
    body = str(text)

    def _pull(pattern: _re.Pattern[str]) -> None:
        nonlocal body

        def _sub(m: _re.Match[str]) -> str:
            inner = (m.group(1) or "").strip()
            if inner:
                thoughts.append(inner)
            return ""

        body = pattern.sub(_sub, body)

    _pull(_re.compile(r"<thought>([\s\S]*?)</thought>", _re.IGNORECASE))
    _pull(_re.compile(r"<redacted_thinking>([\s\S]*?)</redacted_thinking>", _re.IGNORECASE))
    _pull(_re.compile(r"<thinking>([\s\S]*?)</thinking>", _re.IGNORECASE))
    _pull(_re.compile(r"<think>([\s\S]*?)</think>", _re.IGNORECASE))

    # Recover dangling thought tags from truncated local-model generations.
    dangling = _re.search(
        r"<(?:thought|redacted_thinking|thinking|think)>([\s\S]*)$",
        body,
        flags=_re.IGNORECASE,
    )
    if dangling:
        tail = (dangling.group(1) or "").strip()
        if tail:
            thoughts.append(tail)
        body = body[:dangling.start()]

    return thoughts, (body or "").strip()


def coerce_assistant_content_to_text(content: Any) -> str:
    """Normalize provider-specific assistant content payloads to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if text is None:
                    text = item.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        if parts:
            return "\n".join(parts).strip()
    if isinstance(content, dict):
        text = content.get("text")
        if text is None:
            text = content.get("content")
        if isinstance(text, str):
            return text
    return str(content)


def _collect_reasoning_texts(value: Any, out: List[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        txt = value.strip()
        if txt:
            out.append(txt)
        return
    if isinstance(value, list):
        for item in value:
            _collect_reasoning_texts(item, out)
        return
    if isinstance(value, dict):
        for key in ("text", "content", "reasoning", "reasoning_content", "thinking", "thought"):
            if key in value:
                _collect_reasoning_texts(value.get(key), out)
        return


_REASONING_KEYS = frozenset({
    "reasoning", "reasoning_content", "reasoning_details",
    "thinking", "thought", "redacted_thinking",
})

_REASONING_TYPES = frozenset({
    "reasoning", "thinking", "thought", "redacted_thinking",
    "reasoning_content", "reasoning_text",
})

_REASONING_CONTAINER_KEYS = frozenset({
    "content", "contents", "message", "messages",
    "delta", "choices", "choice", "output", "outputs",
    "response", "responses", "item", "items",
    "data", "parts", "chunk",
})


def _collect_reasoning_nodes(value: Any, out: List[str]) -> None:
    """Walk provider payloads and extract only reasoning-related fields."""
    if value is None:
        return
    if isinstance(value, list):
        for item in value:
            _collect_reasoning_nodes(item, out)
        return
    if not isinstance(value, dict):
        return

    node_type = str(value.get("type") or "").strip().lower()
    if node_type in _REASONING_TYPES:
        for key in ("text", "content", "reasoning", "reasoning_content", "thinking", "thought"):
            if key in value:
                _collect_reasoning_texts(value.get(key), out)
        return

    for key, val in value.items():
        key_l = str(key).strip().lower()
        if key_l in _REASONING_KEYS:
            _collect_reasoning_texts(val, out)
        elif key_l in _REASONING_CONTAINER_KEYS:
            _collect_reasoning_nodes(val, out)


def extract_reasoning_from_response(raw: Any) -> List[str]:
    """Extract hidden reasoning/thought text from non-content response fields."""
    out: List[str] = []
    additional = getattr(raw, "additional_kwargs", None)
    if isinstance(additional, dict):
        _collect_reasoning_nodes(additional, out)
    meta = getattr(raw, "response_metadata", None)
    if isinstance(meta, dict):
        _collect_reasoning_nodes(meta, out)
    content = getattr(raw, "content", None)
    if isinstance(content, (list, dict)):
        _collect_reasoning_nodes(content, out)

    uniq: List[str] = []
    seen: set[str] = set()
    for t in out:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


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

# Names local models invent instead of TCA tools (exact map after structural cleanup).
_MALFORMED_TOOL_NAMES: Dict[str, str] = {
    "google:search": "web_search",
    "google_search": "web_search",
    "web-search": "web_search",
    "bing_search": "web_search",
    "internet_search": "web_search",
    "search_web": "web_search",
    "file_manager": "list_files",
    "filesystem_list": "list_files",
}


def sanitize_tool_call_name(raw: str) -> str:
    """Normalize provider-specific / hallucinated tool names (Qwen channel, namespaces, …)."""
    name = str(raw or "").strip()
    if not name:
        return name
    if name in _MALFORMED_TOOL_NAMES:
        return _MALFORMED_TOOL_NAMES[name]
    if "<|channel|>" in name:
        parts = [p.strip() for p in name.split("<|channel|>") if p.strip()]
        if parts:
            name = parts[-1]
    name = name.strip()
    for pref in ("functions.", "function.", "tool.", "tools.", "assistant."):
        if name.startswith(pref):
            name = name[len(pref):].strip()
            break
    return _MALFORMED_TOOL_NAMES.get(name, name)


_TOOL_NAME_ALIASES: Dict[str, str] = {
    # Common hallucinations from local/Ollama models.
    "create_file": "write_file",
    "create_code_file": "code_file_tool",
    "append_code_snippet": "code_file_tool",
    "think": "reasoning_tool",
    "show_diff": "reasoning_tool",
    "analyze_code": "reasoning_tool",
}

_META_TOOL_NAMES = frozenset({"assistant", "tool", "function", "call_tool"})


def _normalize_tool_args(raw_args: Any) -> Dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            try:
                from json_repair import repair_json

                parsed = json.loads(repair_json(raw_args))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        py_kwargs = _parse_python_kwargs(raw_args)
        if py_kwargs:
            return py_kwargs
    return {}


def _coerce_scalar_value(token: str) -> Any:
    s = str(token or "").strip()
    if not s:
        return ""
    lo = s.lower()
    if lo == "true":
        return True
    if lo == "false":
        return False
    if lo in ("none", "null"):
        return None
    try:
        return int(s)
    except Exception:
        pass
    try:
        return float(s)
    except Exception:
        pass
    return s


def _parse_python_kwargs(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip().strip(",")
    if not raw:
        return {}

    try:
        expr = ast.parse(f"f({raw})", mode="eval")
        call = expr.body
        if isinstance(call, ast.Call):
            out: Dict[str, Any] = {}
            for kw in call.keywords:
                if kw.arg is None:
                    continue
                try:
                    out[str(kw.arg)] = ast.literal_eval(kw.value)
                except Exception:
                    if isinstance(kw.value, ast.Constant):
                        out[str(kw.arg)] = kw.value.value
                    else:
                        out[str(kw.arg)] = _coerce_scalar_value(ast.unparse(kw.value))
            if out:
                return out
    except Exception:
        pass

    out: Dict[str, Any] = {}
    pattern = _re.compile(
        r'([A-Za-z_]\w*)\s*=\s*(?:"([^"]*)(?:"|$)|\'([^\']*)(?:\'|$)|([^,]+))(?:\s*,\s*|$)'
    )
    for m in pattern.finditer(raw):
        key = str(m.group(1) or "").strip()
        if not key:
            continue
        if m.group(2) is not None:
            out[key] = m.group(2)
        elif m.group(3) is not None:
            out[key] = m.group(3)
        else:
            out[key] = _coerce_scalar_value(m.group(4) or "")
    return out


def _apply_tool_alias(tool_name: str, args: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    canonical = _TOOL_NAME_ALIASES.get(tool_name, tool_name)
    if canonical == tool_name:
        return canonical, args

    # Backward-compat aliases from older prompts/tool names.
    if tool_name == "create_file":
        path = args.get("path") or args.get("filepath") or args.get("filename") or args.get("file_path") or ""
        content = args.get("content")
        if content is None:
            content = args.get("text", args.get("code", ""))
        return "write_file", {"path": str(path), "content": str(content)}
    if tool_name == "create_code_file":
        filepath = args.get("filepath") or args.get("path") or args.get("filename") or args.get("file_path") or ""
        language = args.get("language", "python")
        code = args.get("code")
        if code is None:
            code = args.get("content", "")
        return "code_file_tool", {
            "action": "create",
            "filepath": str(filepath),
            "language": str(language),
            "code": str(code),
        }
    if tool_name == "append_code_snippet":
        filepath = args.get("filepath") or args.get("path") or args.get("filename") or args.get("file_path") or ""
        language = args.get("language", "python")
        snippet = args.get("snippet")
        if snippet is None:
            snippet = args.get("content", args.get("code", ""))
        return "code_file_tool", {
            "action": "append",
            "filepath": str(filepath),
            "language": str(language),
            "snippet": str(snippet),
        }
    if tool_name == "think":
        thought = args.get("thought") or args.get("input_text") or args.get("content", "")
        return "reasoning_tool", {"action": "think", "thought": str(thought)}
    if tool_name == "show_diff":
        return "reasoning_tool", {
            "action": "diff",
            "path": str(args.get("path", "")),
            "old_content": str(args.get("old_content", "")),
            "new_content": str(args.get("new_content", "")),
        }
    if tool_name == "analyze_code":
        return "reasoning_tool", {
            "action": "analyze",
            "path": str(args.get("path", "")),
            "query": str(args.get("query", "")),
        }
    if tool_name == "get_documentation":
        return "library_context", {
            "action": "search",
            "query": str(args.get("query", "")),
            "library_name": str(args.get("library", args.get("library_name", ""))),
        }
    return canonical, args


def _unwrap_meta_tool_call(tool_name: str, args: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    name = sanitize_tool_call_name(tool_name)
    if not isinstance(args, dict):
        return name, args

    if name in _META_TOOL_NAMES or (not name and (args.get("name") or args.get("tool"))):
        inner_name = sanitize_tool_call_name(str(args.get("name") or args.get("tool") or ""))
        inner_args = dict(args)
        inner_args.pop("name", None)
        inner_args.pop("tool", None)
        if inner_name:
            return inner_name, inner_args

        act = str(args.get("action", "")).strip().lower()
        if act in ("think", "diff", "analyze", "show_diff", "analyze_code"):
            return act, inner_args

        question = args.get("question")
        if isinstance(question, str) and question.strip():
            return "ask_user", {"question": question}

    return name, args


def _strip_glued_ask_user_json_from_thought(thought: str) -> str:
    """Local models often append a second JSON object (e.g. ask_user) inside `thought` without closing the string."""
    t = (thought or "").strip()
    if not t or '{"' not in t:
        return t
    m = _re.search(r'[\s.]*\{\s*"question"\s*:', t, _re.IGNORECASE)
    if m and m.start() > 0:
        return t[: m.start()].rstrip(" .")
    return t


def _repair_reasoning_tool_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """Fix mangled reasoning_tool(think) payloads before schema validation."""
    if not isinstance(args, dict):
        return args
    act = str(args.get("action", "")).strip().lower()
    thought = args.get("thought")
    if not isinstance(thought, str) or not thought.strip():
        return args
    if act not in ("think", ""):
        return args
    if act == "" and (args.get("path") or args.get("query") or args.get("old_content")):
        return args
    cleaned = _strip_glued_ask_user_json_from_thought(thought)
    if cleaned == thought and act != "":
        return args
    out = dict(args)
    out["thought"] = cleaned
    if act == "":
        out["action"] = "think"
    return out


def normalize_tool_call(tc: Any) -> Dict[str, Any]:
    tool_name = ""
    args_raw: Any = {}
    tool_id = ""
    if isinstance(tc, dict):
        tool_name = str(tc.get("name") or tc.get("tool") or "")
        args_raw = tc.get("args") or tc.get("arguments") or {}
        tool_id = str(tc.get("id") or "")
    else:
        tool_name = str(getattr(tc, "name", "") or "")
        args_raw = getattr(tc, "args", {}) or getattr(tc, "arguments", {}) or {}
        tool_id = str(getattr(tc, "id", "") or "")
    tool_name = sanitize_tool_call_name(tool_name)
    args = _normalize_tool_args(args_raw)
    tool_name, args = _unwrap_meta_tool_call(tool_name, args)
    tool_name, args = _apply_tool_alias(tool_name, args)
    if tool_name == "reasoning_tool":
        args = _repair_reasoning_tool_args(args)
    return {"name": tool_name, "args": args, "id": tool_id}


def _normalize_textual_tool_candidate(text: str) -> Dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = raw.strip("`")
    raw = _re.sub(r"^[\s>*\-•]+", "", raw).strip()
    if not raw:
        return None

    call_match = _re.match(r"^([A-Za-z_][\w.]*)\((.*)\)\s*$", raw, flags=_re.DOTALL)
    if call_match:
        tool_name = call_match.group(1)
        args = _parse_python_kwargs(call_match.group(2))
        norm = normalize_tool_call({"name": tool_name, "args": args, "id": ""})
        if norm.get("name") and norm.get("name") not in _META_TOOL_NAMES:
            return norm

    kwargs_src = raw
    prefix_name = ""
    prefix_match = _re.match(r"^([A-Za-z_][\w.]*)\s+(?=[A-Za-z_]\w*\s*=)(.*)$", raw, flags=_re.DOTALL)
    if prefix_match:
        prefix_name = prefix_match.group(1)
        kwargs_src = prefix_match.group(2)

    args = _parse_python_kwargs(kwargs_src)
    if not args:
        return None

    guessed_name = prefix_name
    if not guessed_name:
        if args.get("name") or args.get("tool"):
            guessed_name = "assistant"
        elif args.get("action"):
            guessed_name = "reasoning_tool"
        elif args.get("question"):
            guessed_name = "ask_user"

    norm = normalize_tool_call({"name": guessed_name, "args": args, "id": ""})
    if norm.get("name") and norm.get("name") not in _META_TOOL_NAMES:
        return norm
    return None


def extract_textual_tool_calls(content: str) -> tuple[List[Dict[str, Any]], str]:
    """Recover tool calls from plain-text pseudo-calls emitted by local models."""
    text = str(content or "")
    stripped = text.strip()
    if not stripped:
        return [], text

    direct = _normalize_textual_tool_candidate(stripped)
    if direct is not None:
        return [direct], ""

    calls: List[Dict[str, Any]] = []
    body_lines: List[str] = []
    for line in text.splitlines():
        tc = _normalize_textual_tool_candidate(line.strip())
        if tc is not None:
            calls.append(tc)
        else:
            body_lines.append(line)
    if calls:
        return calls, "\n".join(body_lines).strip()
    return [], text


_JSON_TOOL_ARG_KEYS = frozenset({"args", "arguments", "parameters", "kwargs", "input"})
_JSON_TOOL_WRAPPER_KEYS = frozenset({
    "tool_calls", "tool_call", "call", "calls",
    "message", "messages", "delta", "choices", "choice",
    "output", "outputs", "response", "responses",
    "data", "items", "item", "parts", "content",
})
_TOOL_CALL_TYPES = frozenset({"tool_call", "function_call", "tool_use"})


def _iter_json_tool_candidates(value: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if not isinstance(node, dict):
            return

        node_type = str(node.get("type") or "").strip().lower()
        fn = node.get("function")
        name = node.get("name") or node.get("tool")
        args = None
        for k in _JSON_TOOL_ARG_KEYS:
            if k in node:
                args = node.get(k)
                break
        tid = node.get("id")

        has_tool_shape = False
        if isinstance(fn, dict):
            has_tool_shape = bool(fn.get("name")) or node_type in _TOOL_CALL_TYPES
            if not name:
                name = fn.get("name")
            if args in (None, ""):
                for k in _JSON_TOOL_ARG_KEYS:
                    if k in fn:
                        args = fn.get(k)
                        break
        elif node_type in _TOOL_CALL_TYPES:
            has_tool_shape = True
        elif name and any(k in node for k in _JSON_TOOL_ARG_KEYS):
            has_tool_shape = True

        if has_tool_shape and name:
            out.append({
                "name": str(name),
                "args": args if args is not None else {},
                "id": str(tid or ""),
            })

        for key, val in node.items():
            if str(key).strip().lower() in _JSON_TOOL_WRAPPER_KEYS:
                _walk(val)

    _walk(value)
    return out


def extract_structured_tool_calls(content: str) -> List[Dict[str, Any]]:
    """Recover JSON-structured tool calls from assistant text payload."""
    text = str(content or "")
    if not text.strip():
        return []
    try:
        parsed = json.loads(repair_json(text))
    except Exception:
        return []

    raw_candidates = _iter_json_tool_candidates(parsed)
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for idx, cand in enumerate(raw_candidates):
        norm = normalize_tool_call({
            "name": cand.get("name") or "",
            "args": cand.get("args") or {},
            "id": cand.get("id") or f"call_{idx}",
        })
        name = str(norm.get("name") or "")
        if not name or name in _META_TOOL_NAMES:
            continue
        norm["type"] = "tool_call"
        sig = f"{norm.get('id')}|{name}|{json.dumps(norm.get('args', {}), ensure_ascii=False, sort_keys=True, default=str)}"
        if sig in seen:
            continue
        seen.add(sig)
        out.append(norm)
    return out


_TOOL_RESULT_HINT_KEYS = frozenset({
    "action", "path", "file_path", "total_lines",
    "before_total_lines", "after_total_lines", "delta_total_lines",
    "snapshot_id", "recorded", "stdout", "stderr", "returncode", "entries",
})

_WRITE_ACTIONS = frozenset({
    "written", "edited", "code_written", "snippet_appended",
    "lines_replaced", "lines_inserted", "created", "created_file", "appended",
    "patched",
})


def _parse_json_object_text(text: str) -> Dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw or not raw.startswith(("{", "[")):
        return None
    try:
        parsed = json.loads(repair_json(raw))
    except Exception:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def summarize_tool_like_final_answer(content: str) -> str | None:
    """Convert raw tool-result JSON into a concise user-facing sentence."""
    payload = _parse_json_object_text(content)
    if not isinstance(payload, dict):
        return None
    if not (set(payload.keys()) & _TOOL_RESULT_HINT_KEYS):
        return None

    if payload.get("error"):
        detail = str(payload.get("detail") or payload.get("error"))
        return f"Инструмент вернул ошибку: {detail}"

    path = str(payload.get("path") or payload.get("file_path") or "").strip()
    action = str(payload.get("action") or "").strip().lower()
    total_lines = payload.get("total_lines")

    if path and action in _WRITE_ACTIONS:
        line_part = ""
        try:
            if total_lines is not None:
                line_part = f" ({int(total_lines)} строк)"
        except Exception:
            line_part = ""
        return f"Готово: обновил файл `{path}`{line_part}."

    if path and payload.get("recorded") and isinstance(payload.get("content"), str):
        try:
            inferred_lines = len(str(payload.get("content") or "").splitlines())
        except Exception:
            inferred_lines = 0
        line_part = f" ({inferred_lines} строк)" if inferred_lines > 0 else ""
        return f"Готово: подготовил файл `{path}`{line_part}."

    if path and action:
        return f"Готово: {action} для `{path}`."

    return None


def coalesce_lc_response_tool_calls(raw: Any) -> List[Any]:
    """Return tool_calls from a LangChain chat-model response, with Ollama recovery.

    Ollama's OpenAI-compatible endpoint may return ``function.arguments`` as a JSON
    **object** instead of a string. LangChain's OpenAI converter then fails
    ``json.loads(arguments)``, stores the call in ``invalid_tool_calls``, and leaves
    ``tool_calls`` empty — so the agent never runs tools. We recover dict (and valid
    JSON string) arguments from ``invalid_tool_calls`` into normal tool call dicts.
    """
    def _parse_args(raw_args: Any) -> Dict[str, Any]:
        return _normalize_tool_args(raw_args)

    def _dedupe_calls(calls: List[dict]) -> List[dict]:
        uniq: List[dict] = []
        seen: set[str] = set()
        for call in calls:
            sig = (
                f"{call.get('id','')}|{call.get('name','')}|"
                f"{json.dumps(call.get('args', {}), ensure_ascii=False, sort_keys=True, default=str)}"
            )
            if sig in seen:
                continue
            seen.add(sig)
            uniq.append(call)
        return uniq

    def _coerce_call(call: Any, idx: int) -> dict | None:
        if isinstance(call, dict):
            call_dict = call
            fn = call_dict.get("function")
            name = call_dict.get("name") or call_dict.get("tool")
            args = call_dict.get("args")
            if args is None:
                args = call_dict.get("arguments")
            tid = call_dict.get("id")
            if isinstance(fn, dict):
                if not name:
                    name = fn.get("name")
                if args in (None, ""):
                    args = fn.get("arguments")
        else:
            fn = getattr(call, "function", None)
            name = getattr(call, "name", None) or getattr(call, "tool", None)
            args = getattr(call, "args", None)
            if args is None:
                args = getattr(call, "arguments", None)
            tid = getattr(call, "id", None)
            if fn is not None:
                fn_name = getattr(fn, "name", None)
                fn_args = getattr(fn, "arguments", None)
                if isinstance(fn, dict):
                    fn_name = fn.get("name", fn_name)
                    fn_args = fn.get("arguments", fn_args)
                if not name:
                    name = fn_name
                if args in (None, ""):
                    args = fn_args
        name_s = sanitize_tool_call_name(str(name or "").strip())
        if not name_s:
            return None
        normalized = normalize_tool_call({
            "name": name_s,
            "args": _parse_args(args),
            "id": str(tid or f"call_{idx}"),
        })
        normalized["type"] = "tool_call"
        return normalized

    def _collect_nested_provider_calls(value: Any, out: List[Any]) -> None:
        if isinstance(value, list):
            for item in value:
                _collect_nested_provider_calls(item, out)
            return
        if not isinstance(value, dict):
            return

        t = str(value.get("type") or "").strip().lower()
        if t in _TOOL_CALL_TYPES:
            out.append(value)

        if isinstance(value.get("function"), dict) and (
            value.get("name")
            or value.get("tool")
            or value["function"].get("name")
        ):
            out.append(value)

        maybe_calls = value.get("tool_calls")
        if isinstance(maybe_calls, list):
            out.extend(maybe_calls)

        for key, val in value.items():
            key_l = str(key).strip().lower()
            if key_l in _JSON_TOOL_WRAPPER_KEYS:
                _collect_nested_provider_calls(val, out)

    primary = list(getattr(raw, "tool_calls", None) or [])
    primary_out: List[dict] = []
    for idx, call in enumerate(primary):
        parsed = _coerce_call(call, idx)
        if parsed is not None:
            primary_out.append(parsed)
    if primary_out:
        return _dedupe_calls(primary_out)

    recovered: List[dict] = []
    for inv in getattr(raw, "invalid_tool_calls", None) or []:
        parsed = _coerce_call(inv, len(recovered))
        if parsed is not None:
            recovered.append(parsed)

    if recovered:
        return _dedupe_calls(recovered)

    additional = getattr(raw, "additional_kwargs", None)
    meta = getattr(raw, "response_metadata", None)
    content = getattr(raw, "content", None)

    nested_calls: List[Any] = []
    if isinstance(additional, dict):
        _collect_nested_provider_calls(additional, nested_calls)
    if isinstance(meta, dict):
        _collect_nested_provider_calls(meta, nested_calls)
    if isinstance(content, (dict, list)):
        _collect_nested_provider_calls(content, nested_calls)
    if nested_calls:
        out: List[dict] = []
        for idx, call in enumerate(nested_calls):
            parsed = _coerce_call(call, idx)
            if parsed is not None:
                out.append(parsed)
        if out:
            return _dedupe_calls(out)

    return []


# ─── Broken JSON reconstruction ────────────────────────────────────

_CONTENT_FIELD_MAP = {
    "write_file": ("content", {"path"}),
    "create_code_file": ("code", {"filepath", "language"}),
    "append_code_snippet": ("snippet", {"filepath", "language"}),
    "docx_write_tool": ("data_json", {"file_path", "action"}),
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
    "ocr_tool": 9000,
    "ocr_read_file_soft": 7000,
    "ocr_read_image_medium": 7000,
    "ocr_read_photo_strong": 9000,
    "office_document_read": 10_000,
    "docx_write_tool": 4000,
    "docx_document_create": 4000,
    "docx_document_append_paragraphs": 4000,
    "docx_document_patch_paragraphs": 4000,
    "docxedit_tool": 4000,
    "docx_document_advanced_ops": 6000,
    "pdf_styled_document_create": 4000,
    "plan_tool": 4000,
    "git_ops": 5000,
    "library_context": 12_000,
    "reasoning_tool": 6000,
    "code_file_tool": 4000,
    "headless_browser": 8000,
    "playwright_sync": 8000,
    "file_versions_tool": 4000,
}
DEFAULT_RESULT_LIMIT = 3000

_WEB_COMPACT_TOOLS = frozenset({"web_search", "web_fetch", "web_search_and_read"})
_OCR_COMPACT_TOOLS = frozenset({
    "ocr_tool",
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
