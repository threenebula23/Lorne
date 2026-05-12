"""Message sanitization, compaction, and tool result processing utilities."""
import ast
import json
import re as _re
import uuid
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


_HARMONY_CHANNEL_RE = _re.compile(
    r"<\|channel\|>\s*(?P<channel>[A-Za-z_]+)\s*(?:<\|constrain\|>[^<]*)?"
    r"<\|message\|>(?P<body>[\s\S]*?)"
    r"(?=<\|(?:start|channel|end|return|call|message)\|>|\Z)",
    flags=_re.IGNORECASE,
)
_HARMONY_META_TOKEN_RE = _re.compile(
    r"<\|(?:start|end|return|call|constrain|message|channel)\|>[^<]*",
    flags=_re.IGNORECASE,
)
_HARMONY_HIDDEN_CHANNELS = frozenset({"analysis", "commentary", "thinking", "thoughts"})


def _extract_harmony_segments(text: str) -> tuple[List[str], str]:
    """Split gpt-oss/Harmony messages into (hidden_reasoning, visible_body)."""
    raw = str(text or "")
    if "<|channel|>" not in raw and "<|message|>" not in raw:
        return [], raw

    thoughts: List[str] = []
    visible: List[str] = []
    last_end = 0
    found = False
    for m in _HARMONY_CHANNEL_RE.finditer(raw):
        found = True
        last_end = m.end()
        channel = (m.group("channel") or "").strip().lower()
        body = (m.group("body") or "").strip()
        if not body:
            continue
        if channel in _HARMONY_HIDDEN_CHANNELS:
            thoughts.append(body)
        else:
            visible.append(body)

    if not found:
        # Stray Harmony tokens only — just strip them out.
        cleaned = _HARMONY_META_TOKEN_RE.sub("", raw).strip()
        return [], cleaned

    tail = raw[last_end:].strip()
    if tail:
        tail_clean = _HARMONY_META_TOKEN_RE.sub("", tail).strip()
        if tail_clean:
            # Anything after the last known channel marker is usually final output.
            visible.append(tail_clean)

    body = "\n".join(part for part in visible if part).strip()
    return thoughts, body


# XML-style reasoning tags emitted by various models. `thought`/`think`/`thinking`
# are the TCA/DeepSeek/Qwen/Anthropic convention; `reasoning`/`analysis`/
# `scratchpad` show up in smaller local models (Mistral-family, ReAct fine-tunes);
# `redacted_thinking` is Anthropic's encrypted variant.
_REASONING_XML_TAGS = (
    "redacted_thinking",
    "thinking",
    "think",
    "thought",
    "reasoning",
    "analysis",
    "scratchpad",
)
_REASONING_XML_ALT_GROUP = "|".join(_REASONING_XML_TAGS)

# Qwen/ChatML-style pipe tokens:  <|thinking|> ... <|/thinking|>
_REASONING_PIPE_TAGS = ("thinking", "think", "thought", "reasoning")
_REASONING_PIPE_ALT_GROUP = "|".join(_REASONING_PIPE_TAGS)

# Bracketed markers emitted by some local/finetuned models:
#   [THINKING] ... [/THINKING], [THOUGHT] ... [/THOUGHT], [REASONING] ... [/REASONING]
_REASONING_BRACKET_TAGS = ("thinking", "thought", "reasoning")
_REASONING_BRACKET_ALT_GROUP = "|".join(_REASONING_BRACKET_TAGS)


def _reasoning_tag_patterns() -> List[_re.Pattern[str]]:
    """Build the list of regexes that capture reasoning segments in text."""
    return [
        _re.compile(rf"<({_REASONING_XML_ALT_GROUP})>([\s\S]*?)</\1>", _re.IGNORECASE),
        _re.compile(
            rf"<\|({_REASONING_PIPE_ALT_GROUP})\|>([\s\S]*?)<\|/\1\|>",
            _re.IGNORECASE,
        ),
        _re.compile(
            rf"\[\s*({_REASONING_BRACKET_ALT_GROUP})\s*\]([\s\S]*?)\[\s*/\s*\1\s*\]",
            _re.IGNORECASE,
        ),
    ]


# Pre-compiled once; patterns are static so we can safely cache them.
_REASONING_TAG_PATTERNS = _reasoning_tag_patterns()

# Dangling opener with no closer — keep this lenient because local models
# frequently stop mid-stream and leave the tag open.
_REASONING_DANGLING_RE = _re.compile(
    rf"(?:<({_REASONING_XML_ALT_GROUP})>"
    rf"|<\|({_REASONING_PIPE_ALT_GROUP})\|>"
    rf"|\[\s*({_REASONING_BRACKET_ALT_GROUP})\s*\])([\s\S]*)$",
    _re.IGNORECASE,
)


def strip_think_tags(text: str) -> str:
    """Remove every reasoning wrapper from visible output.

    Covers XML-style tags (<think>, <thinking>, <thought>, <reasoning>,
    <analysis>, <scratchpad>, <redacted_thinking>), Qwen pipe tags
    (<|thinking|>…<|/thinking|>), bracketed markers ([THINKING]…[/THINKING]),
    unclosed/dangling variants, and Harmony/gpt-oss channel blocks.
    """
    out = str(text or "")
    for pat in _REASONING_TAG_PATTERNS:
        out = pat.sub("", out)
    out = _REASONING_DANGLING_RE.sub("", out)
    # Harmony / gpt-oss tokens (<|channel|>analysis<|message|>…) — strip any
    # leftovers if the caller didn't go through extract_thought_segments first.
    if "<|" in out:
        _, body = _extract_harmony_segments(out)
        out = body if body else _HARMONY_META_TOKEN_RE.sub("", out)
    return out.strip()


def extract_thought_segments(text: str) -> tuple[List[str], str]:
    """Split raw model output into (thought_segments, visible_body).

    Recognised reasoning wrappers (all case-insensitive, content preserved in
    emission order):
      - XML: <thought>, <think>, <thinking>, <reasoning>, <analysis>,
        <scratchpad>, <redacted_thinking>
      - Qwen/ChatML pipe tokens: <|thinking|>…<|/thinking|>, <|think|>…
      - Bracketed markers: [THINKING]…[/THINKING], [THOUGHT]…, [REASONING]…
      - Harmony / gpt-oss channels: <|channel|>analysis<|message|>…
      - Unclosed tags left at the tail of a truncated generation.
    """
    if not (text or "").strip():
        return [], text or ""
    thoughts: List[str] = []
    body = str(text)

    def _sub_capture(m: _re.Match[str]) -> str:
        # Reasoning content is always the *last* capture group in our patterns
        # (the first groups capture the tag name for the back-reference).
        inner = (m.group(m.lastindex) if m.lastindex else m.group(0)).strip()
        if inner:
            thoughts.append(inner)
        return ""

    for pat in _REASONING_TAG_PATTERNS:
        body = pat.sub(_sub_capture, body)

    dangling = _REASONING_DANGLING_RE.search(body)
    if dangling:
        tail = (dangling.group(dangling.lastindex) or "").strip()
        if tail:
            thoughts.append(tail)
        body = body[: dangling.start()]

    if "<|" in body:
        harmony_thoughts, harmony_body = _extract_harmony_segments(body)
        if harmony_thoughts or harmony_body != body:
            thoughts.extend(harmony_thoughts)
            body = harmony_body

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


_REASONING_TEXT_KEYS = (
    "text", "content", "reasoning", "reasoning_content",
    "thinking", "thought", "summary_text", "summary",
    "tool_plan", "plan",
)


def _collect_reasoning_texts(value: Any, out: List[str]) -> None:
    """Collect textual reasoning fragments from arbitrary nested values.

    Bool values (e.g. Gemini's `"thought": true` flag marking a part as a
    thought) carry no text — the caller handles them upstream in
    `_collect_reasoning_nodes`.
    """
    if value is None or isinstance(value, bool):
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
        for key in _REASONING_TEXT_KEYS:
            if key in value:
                _collect_reasoning_texts(value.get(key), out)
        return


# Top-level keys anywhere in provider payloads that directly carry reasoning.
#   - `reasoning` / `reasoning_content`: OpenAI o-series, DeepSeek-R1, OpenRouter
#   - `reasoning_details`: ChatOpenAI passthrough
#   - `reasoning_summary`: OpenAI Responses API summary
#   - `thinking`, `thought`, `redacted_thinking`: Anthropic, TCA, misc.
#   - `tool_plan`: Cohere Command R/Plus emits this before tool calls
#   - `analysis`, `scratchpad`: occasional small-model schemas
_REASONING_KEYS = frozenset({
    "reasoning", "reasoning_content", "reasoning_details",
    "reasoning_summary",
    "thinking", "thought", "redacted_thinking",
    "tool_plan",
    "analysis", "scratchpad",
})

_REASONING_TYPES = frozenset({
    "reasoning", "thinking", "thought", "redacted_thinking",
    "reasoning_content", "reasoning_text",
    "analysis",
})

_REASONING_CONTAINER_KEYS = frozenset({
    "content", "contents", "message", "messages",
    "delta", "choices", "choice", "output", "outputs",
    "response", "responses", "item", "items",
    "data", "parts", "chunk",
    # OpenAI Responses API reasoning summary bucket.
    "summary",
})


def _is_gemini_thought_part(value: Dict[str, Any]) -> bool:
    """Detect Gemini `thinkingConfig` parts: {"thought": true, "text": "..."}.

    Gemini doesn't use a distinct type/channel; it flips a boolean flag on an
    otherwise regular text part. Without this shortcut we'd drop the text.
    """
    if not isinstance(value, dict):
        return False
    flag = value.get("thought")
    if flag is True:
        return True
    if isinstance(flag, str) and flag.strip().lower() == "true":
        return True
    return False


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
        for key in _REASONING_TEXT_KEYS:
            if key in value:
                _collect_reasoning_texts(value.get(key), out)
        return

    # Gemini `thinkingConfig` shape: {"thought": True, "text": "..."}
    if _is_gemini_thought_part(value):
        for key in ("text", "content", "reasoning", "reasoning_content"):
            if key in value:
                _collect_reasoning_texts(value.get(key), out)
        # Don't descend further — the remaining keys are metadata.
        return

    for key, val in value.items():
        key_l = str(key).strip().lower()
        if key_l in _REASONING_KEYS:
            _collect_reasoning_texts(val, out)
        elif key_l in _REASONING_CONTAINER_KEYS:
            _collect_reasoning_nodes(val, out)


def extract_message_usage(msg: Any) -> Dict[str, int]:
    """Return {'input_tokens', 'output_tokens', 'total_tokens'} for an AIMessage.

    Supports multiple provider shapes:
      - LangChain `usage_metadata` attribute (standard, emitted by ChatOllama/ChatOpenAI)
      - `response_metadata.usage` / `response_metadata.token_usage` (OpenAI-compat)
      - Ollama native `response_metadata.prompt_eval_count` + `eval_count`
    Returns zero counts when nothing is available.
    """
    out = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if msg is None:
        return out

    um = getattr(msg, "usage_metadata", None)
    if isinstance(um, dict):
        inp = int(um.get("input_tokens") or 0)
        outp = int(um.get("output_tokens") or 0)
        tot = int(um.get("total_tokens") or 0) or (inp + outp)
        if inp or outp or tot:
            return {"input_tokens": inp, "output_tokens": outp, "total_tokens": tot}

    meta = getattr(msg, "response_metadata", None) or {}
    if isinstance(meta, dict):
        usage = meta.get("usage") or meta.get("token_usage") or {}
        if isinstance(usage, dict):
            inp = int(
                usage.get("prompt_tokens")
                or usage.get("input_tokens")
                or 0
            )
            outp = int(
                usage.get("completion_tokens")
                or usage.get("output_tokens")
                or 0
            )
            tot = int(usage.get("total_tokens") or 0) or (inp + outp)
            if inp or outp or tot:
                return {"input_tokens": inp, "output_tokens": outp, "total_tokens": tot}

        # Native Ollama (/api/chat) exposes these top-level counters.
        inp = int(meta.get("prompt_eval_count") or 0)
        outp = int(meta.get("eval_count") or 0)
        if inp or outp:
            return {
                "input_tokens": inp,
                "output_tokens": outp,
                "total_tokens": inp + outp,
            }

    return out


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
    "find": "find_in_file",
    "grep": "find_in_file",
    "file_search": "find_in_file",
}

_META_TOOL_NAMES = frozenset({"assistant", "tool", "function", "call_tool"})


# ─── Known tool registry (populated at runtime from tool_registry) ──────
# Used to reject line-by-line textual tool-call false positives like
# `if b=0`, `print(...)`, `sys.exit(1)` emitted inside code blocks.
_KNOWN_TOOL_NAMES: set[str] = set()


def register_known_tool_names(names: Any) -> None:
    """Record the list of real tool names available in the current session."""
    try:
        items = list(names or [])
    except Exception:
        return
    cleaned: set[str] = set()
    for item in items:
        if not item:
            continue
        cleaned.add(str(item).strip())
    if cleaned:
        _KNOWN_TOOL_NAMES.clear()
        _KNOWN_TOOL_NAMES.update(cleaned)


def _is_registered_tool(name: str) -> bool:
    n = str(name or "").strip()
    if not n:
        return False
    if not _KNOWN_TOOL_NAMES:
        # Registry not populated yet — be permissive so startup paths keep working.
        return True
    if n in _KNOWN_TOOL_NAMES:
        return True
    # Tool may arrive under a canonical name after alias normalization.
    alias = _TOOL_NAME_ALIASES.get(n)
    return bool(alias and alias in _KNOWN_TOOL_NAMES)


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


