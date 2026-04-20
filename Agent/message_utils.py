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


def tool_repetition_loop_nudge(
    messages: List[Any],
    *,
    min_identical: int = 5,
    lookback_messages: int = 24,
) -> str:
    """When the model repeats the same tool+args many times, return an anti-loop hint (ephemeral)."""
    if min_identical < 3:
        return ""
    tail = messages[-max(8, lookback_messages) :]
    sigs: List[str] = []
    for m in tail:
        if not isinstance(m, AIMessage):
            continue
        for tc in getattr(m, "tool_calls", None) or []:
            try:
                n = normalize_tool_call(tc)
                na = str(n.get("name") or "")
                args = n.get("args") or {}
                sig = f"{na}|{json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)[:800]}"
                sigs.append(sig)
            except Exception:
                continue
    if len(sigs) < min_identical:
        return ""
    last = sigs[-1]
    if last and sigs[-min_identical:].count(last) >= min_identical:
        return (
            "СТОП-ПЕТЛЯ: тот же вызов инструмента повторяется много раз подряд. "
            "Не дублируй с теми же аргументами. Смени стратегию: "
            "`web_search` + `web_fetch` по ошибке/доке; другой `read_file` / путь; "
            "`start_background_task` для параллельного теста, пока длинный `run_command` "
            "занят; перепиши команду или разбей задачу."
        )
    return ""


def _normalize_textual_tool_candidate(
    text: str, *, strict: bool = False,
) -> Dict[str, Any] | None:
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
        final_name = str(norm.get("name") or "")
        if final_name and final_name not in _META_TOOL_NAMES:
            if not strict or _is_registered_tool(final_name):
                return norm
        # In strict mode, `print(...)` / `sys.exit(...)` would otherwise be
        # misread as tool calls. Fall through (and ultimately return None).

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
    final_name = str(norm.get("name") or "")
    if not final_name or final_name in _META_TOOL_NAMES:
        return None
    if strict and not _is_registered_tool(final_name):
        return None
    return norm


def extract_textual_tool_calls(content: str) -> tuple[List[Dict[str, Any]], str]:
    """Recover tool calls from plain-text pseudo-calls emitted by local models."""
    text = str(content or "")
    stripped = text.strip()
    if not stripped:
        return [], text

    # Direct mode: entire payload is a single call. Tolerated for short blobs
    # (e.g. `assistant name='ask_user', question='...'`), but not for arbitrary
    # multi-line code dumps where local models append markdown/Python after the
    # real answer.
    direct_strict = "\n" in stripped
    direct = _normalize_textual_tool_candidate(stripped, strict=direct_strict)
    if direct is not None:
        return [direct], ""

    # Line-by-line mode is strict so lines like `if b=0`, `print(...)`,
    # `sys.exit(1)` emitted inside a code block don't get misread as tool calls.
    calls: List[Dict[str, Any]] = []
    body_lines: List[str] = []
    for line in text.splitlines():
        tc = _normalize_textual_tool_candidate(line.strip(), strict=True)
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
    "read_file_lines": 6000,
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

def _compact_tool_result_for_summary(msg: ToolMessage, per_msg_limit: int = 240) -> str:
    """Compact a single tool result to a short excerpt for the summary block.

    Large tool results (file reads, web fetches, OCR) dominate the context;
    once they're old enough to be compacted we only keep a short head + tail
    so the model still knows what happened without re-reading ~10k characters.
    """
    name = getattr(msg, "name", "tool") or "tool"
    content = str(getattr(msg, "content", "") or "").strip()
    if not content:
        return f"  [tool result: {name}] (empty)"
    if len(content) <= per_msg_limit:
        return f"  [tool result: {name}] {content}"
    half = per_msg_limit // 2
    return (
        f"  [tool result: {name}] {content[:half]} … "
        f"[+{len(content) - per_msg_limit} симв.] … {content[-half:]}"
    )


def compact_conversation(
    messages: List[Any],
    keep_last: int = 8,
    *,
    user_text_limit: int = 400,
    assistant_text_limit: int = 400,
    tool_text_limit: int = 240,
) -> List[Any]:
    """Summarize old messages to free up context window.

    Default `keep_last=8` (was 10) because tool results are the main context
    hog — holding fewer full-fidelity turns while summarising the rest with a
    tiny excerpt of every old tool result scales much better for long
    coding sessions.
    """
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

    summary_parts: List[str] = []
    for msg in old_msgs:
        if isinstance(msg, HumanMessage):
            text = (msg.content or "").strip()
            if text:
                summary_parts.append(f"User: {text[:user_text_limit]}")
        elif isinstance(msg, AIMessage):
            text = (msg.content or "").strip()
            if text:
                summary_parts.append(f"Assistant: {text[:assistant_text_limit]}")
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    n = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                    summary_parts.append(f"  [tool call: {n}]")
        elif isinstance(msg, ToolMessage):
            summary_parts.append(
                _compact_tool_result_for_summary(msg, per_msg_limit=tool_text_limit)
            )

    summary_text = (
        "=== CONVERSATION HISTORY (compacted) ===\n"
        "The following is a summary of earlier conversation:\n\n"
        + "\n".join(summary_parts[-60:])
        + "\n\n=== END OF HISTORY ===\n"
        "Continue from here."
    )

    compacted = system_msgs + [HumanMessage(content=summary_text)] + recent_msgs
    return compacted
