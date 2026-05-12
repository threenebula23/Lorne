"""Вторая половина утилит сообщений (после :func:`~Agent.message_utils._impl_low.normalize_tool_call`)."""

from __future__ import annotations

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

from ._impl_low import (
    _META_TOOL_NAMES,
    _is_registered_tool,
    _normalize_tool_args,
    _parse_python_kwargs,
    normalize_tool_call,
    sanitize_tool_call_name,
)

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


def extract_structured_tool_calls(
    content: str,
    allow_implicit_write: bool = True,
) -> List[Dict[str, Any]]:
    """Recover JSON-structured tool calls from assistant text payload."""
    _ = allow_implicit_write  # Backward-compat arg for older call sites.
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


def extract_inline_write_file_args(content: str) -> Dict[str, Any] | None:
    """Best-effort recovery of inline write_file payloads from plain text."""
    text = str(content or "").strip()
    if not text:
        return None

    # 1) Raw JSON object with path/content-like keys.
    payload = _parse_json_object_text(text)
    if isinstance(payload, dict):
        path = payload.get("path") or payload.get("filepath") or payload.get("file_path")
        body = payload.get("content")
        if body is None:
            body = payload.get("text", payload.get("code"))
        if isinstance(path, str) and path.strip() and isinstance(body, str):
            return {"path": path.strip(), "content": body}

    # 2) Python-like pseudo-call: write_file(path="...", content="...").
    m = _re.search(r"write_file\s*\(([\s\S]*?)\)\s*$", text, flags=_re.IGNORECASE)
    if m:
        parsed = _parse_python_kwargs(m.group(1))
        path = parsed.get("path") or parsed.get("filepath") or parsed.get("file_path")
        body = parsed.get("content")
        if body is None:
            body = parsed.get("text", parsed.get("code"))
        if isinstance(path, str) and path.strip() and isinstance(body, str):
            return {"path": path.strip(), "content": body}

    # 3) Markdown style:
    #    path: foo/bar.py
    #    ```python
    #    ...
    #    ```
    path_match = _re.search(
        r"(?im)^\s*(?:path|filepath|file_path|file)\s*:\s*(.+?)\s*$",
        text,
    )
    code_match = _re.search(r"```(?:[^\n]*)\n([\s\S]*?)```", text)
    if path_match and code_match:
        path = (path_match.group(1) or "").strip().strip("`\"'")
        body = code_match.group(1)
        if path:
            return {"path": path, "content": body}

    return None


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


# ─── Ollama: recover tool calls from `error parsing tool call: raw=...` ─

_BT = "\u0060"  # backtick — in JSON, `\`+backtick` is an invalid escape (Ollama/Go error).


def _first_balanced_json_object_from(s: str, i: int) -> str | None:
    """Brace-match a JSON object starting at s[i] == '{', string/escape aware."""
    if i < 0 or i >= len(s) or s[i] != "{":
        return None
    depth = 0
    p = i
    n = len(s)
    in_str = False
    esc = False
    while p < n:
        c = s[p]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[i : p + 1]
        p += 1
    return None


def _first_balanced_json_object(s: str) -> str | None:
    j = s.find("{")
    if j < 0:
        return None
    return _first_balanced_json_object_from(s, j)


def _object_blob_loose(s: str, start_idx: int) -> str | None:
    """Prefer balanced ``{...}``; if tokenizer fails (bad quotes), use first ``{`` … last ``}``."""
    if start_idx < 0 or start_idx >= len(s) or s[start_idx] != "{":
        return None
    bal = _first_balanced_json_object_from(s, start_idx)
    if bal:
        return bal
    j = s.rfind("}", start_idx)
    if j > start_idx:
        return s[start_idx : j + 1]
    return None


def _mend_json_invalid_backslash_before_backtick(s: str) -> str:
    """In JSON string values, a lone ``\\` `` is invalid; models emit this for ``` fences."""
    t = s
    if _BT in t and "\\" in t:
        t = t.replace("\\" + _BT, "\\\\" + _BT)
    return t


def _mend_json_key_equals_scalar(s: str) -> str:
    """Fix ``key=value`` (Python/ini style) where JSON requires ``\"key\": value``."""
    t = s
    pat = _re.compile(
        r"([{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
        r"(true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?)"
        r'(?=\s*[,}"])',
    )
    pat_stray = _re.compile(
        r'([{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'
        r'(-?(?:0|[1-9]\d*)(?:\.\d+)?)\s*"\s*}'
    )
    prev = None
    while prev != t:
        prev = t
        def _stray_fix(m: Any) -> str:
            return m.group(1) + ' "' + m.group(2) + '": ' + m.group(3) + "}"
        t = pat_stray.sub(_stray_fix, t)
        t = pat.sub(lambda m: f'{m.group(1)} "{m.group(2)}": {m.group(3)}', t)
    return t


def _mend_tool_call_json_blob(s: str) -> str:
    """Apply mends that are safe for a single object literal from a tool-call error line."""
    t = str(s or "")
    t = _mend_json_invalid_backslash_before_backtick(t)
    t = _mend_json_key_equals_scalar(t)
    return t


def _parse_tool_error_raw_json_blob(msg: str) -> str | None:
    """Extract JSON from Ollama: ``error parsing tool call: raw='{...'`` (or unquoted)."""
    s = str(msg)
    m = _re.search(r"(?i)raw\s*=\s*'\s*(\{)", s)
    if m:
        return _object_blob_loose(s, m.start(1))
    m2 = _re.search(r'(?i)raw\s*=\s*"\s*(\{)', s)
    if m2:
        return _object_blob_loose(s, m2.start(1))
    m3 = _re.search(r"(?i)raw\s*=\s*(\{)", s)
    if m3:
        return _object_blob_loose(s, m3.start(1))
    j0 = s.find("{")
    if j0 < 0:
        return None
    return _object_blob_loose(s, j0)


def build_aimessage_from_ollama_tool_parse_error(exc: BaseException) -> Any | None:
    """If Ollama could not parse tool call JSON, rebuild :class:`AIMessage` for one tool."""
    em = str(exc)
    e_low = em.lower()
    if "parsing tool call" not in e_low and "tool call" not in e_low:
        return None
    if "raw" not in e_low:
        return None
    blob = _parse_tool_error_raw_json_blob(em)
    if not blob:
        return None
    mended = _mend_json_invalid_backslash_before_backtick(blob)

    def _try_parse_object(raw: str) -> dict | None:
        seq = (
            raw,
            _mend_json_invalid_backslash_before_backtick(raw),
            _mend_json_key_equals_scalar(raw),
            _mend_tool_call_json_blob(raw),
        )
        for cand in seq:
            for r in (cand, repair_json(cand)):
                try:
                    o = json.loads(r)
                    if isinstance(o, dict):
                        return o
                except Exception:
                    try:
                        o = json.loads(repair_json(cand))
                        if isinstance(o, dict):
                            return o
                    except Exception:
                        pass
        return None

    d = _try_parse_object(mended) or _try_parse_object(blob)
    if not isinstance(d, dict):
        return None

    if isinstance(d.get("name"), str) and d.get("arguments") is not None:
        n = sanitize_tool_call_name(d["name"])
        args0 = d["arguments"]
        if isinstance(args0, str):
            a2 = _mend_json_invalid_backslash_before_backtick(args0)
            a = _normalize_tool_args(a2)
        elif isinstance(args0, dict):
            a = dict(args0)
        else:
            a = _normalize_tool_args(str(args0))
        if n and isinstance(a, dict):
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": n,
                    "args": a,
                    "id": f"recov_{uuid.uuid4().hex[:10]}",
                }],
            )
    p, c = d.get("path"), d.get("content")
    if isinstance(p, str) and isinstance(c, str) and p.strip():
        wargs = reconstruct_broken_content(
            "write_file", {"path": p.strip(), "content": c},
        )
        return AIMessage(
            content="",
            tool_calls=[{
                "name": "write_file",
                "args": wargs,
                "id": f"recov_{uuid.uuid4().hex[:10]}",
            }],
        )
    # Flat arguments blob (Ollama failed before wrapping name/arguments).
    if isinstance(d.get("command"), str) and d.get("command", "").strip():
        a: Dict[str, Any] = {
            "command": str(d["command"]).strip(),
            "cwd": str(d.get("cwd") or ".").strip() or ".",
            "background": bool(d.get("background", False)),
        }
        to = d.get("timeout_seconds")
        if to is not None:
            try:
                a["timeout_seconds"] = int(to)
            except (TypeError, ValueError):
                a["timeout_seconds"] = 120
        return AIMessage(
            content="",
            tool_calls=[{
                "name": "run_command",
                "args": a,
                "id": f"recov_{uuid.uuid4().hex[:10]}",
            }],
        )
    return None


def safe_chat_invoke_with_tool_recovery(llm: Any, messages: list, **kwargs: Any) -> Any:
    """``llm.invoke``; on Ollama tool-call parse errors, recover a synthetic ``AIMessage``."""
    try:
        return llm.invoke(messages, **kwargs)
    except Exception as e:
        recovered = build_aimessage_from_ollama_tool_parse_error(e)
        if recovered is not None:
            try:
                print_warning(
                    "Восстановлен вызов инструмента: в tool call был битый JSON "
                    "(``\\` `` в markdown, ``key=значение`` вместо ``\\\"key\\\":`` и т.п.)."
                )
            except Exception:
                pass
            return recovered
        raise


# ─── Token-saving: truncate large tool results ─────────────────────

TOOL_RESULT_LIMITS: Dict[str, int] = {
    "read_file": 4000,
    "read_file_lines": 6000,
    "search_in_files": 3000,
    "find_in_file": 8000,
    "run_command": 3000,
    "list_files": 2000,
    "rag_search": 3000,
    "project_brain_tool": 1200,
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
