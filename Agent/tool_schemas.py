"""Pydantic-схемы аргументов инструментов: валидация, сжатие лишних полей, подсказки модели.

Используется в graph_runner перед invoke — снижает число «битых» вызовов без потери выразительности.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Tuple, Type

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

# ─── Базовые модели по частым тулам ─────────────────────────────────


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    # В коде тула параметр называется `filename`; модели часто шлют `path`.
    filename: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices(
            "filename", "path", "file_path", "filepath", "file",
        ),
    )
    encoding: str = Field(default="utf-8", max_length=32)
    offset: int = Field(default=0, ge=0, le=500_000, description="Номер начальной строки (0-based)")
    limit: int = Field(default=0, ge=0, le=5000, description="Сколько строк; 0 = весь файл")


class ReadFileLinesArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    filename: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices(
            "filename", "path", "file_path", "filepath", "file",
        ),
    )
    start_line: int = Field(
        default=1, ge=1, le=1_000_000,
        description="Первая строка (1-based, включительно)",
        validation_alias=AliasChoices("start_line", "start", "from_line", "begin"),
    )
    end_line: int = Field(
        default=0, ge=0, le=1_000_000,
        description="Последняя строка (включительно, 0 = до конца)",
        validation_alias=AliasChoices("end_line", "end", "to_line", "finish"),
    )
    encoding: str = Field(default="utf-8", max_length=32)


class ListFilesArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    path: str = Field(
        default=".",
        min_length=0,
        max_length=2048,
        validation_alias=AliasChoices("path", "directory", "dir", "folder"),
    )
    recursive: bool = False
    pattern: str = Field(default="*", max_length=256)

    @field_validator("path", mode="before")
    @classmethod
    def _coerce_list_path(cls, v: Any) -> str:
        s = str(v or "").strip()
        return s if s else "."


class SearchInFilesArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    directory: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices("directory", "path", "dir", "folder"),
    )
    query: str = Field(..., min_length=1, max_length=500, description="Текст для поиска (коротко)")
    file_pattern: str = Field(default="*.py", max_length=128)
    max_files: int = Field(default=50, ge=1, le=200)


class EditFileArgs(BaseModel):
    """Совпадает с `edit_file(path, old_str, new_str)` в file_ops.py."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    path: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices("path", "filename", "file_path"),
    )
    old_str: str = Field(
        ...,
        max_length=500_000,
        validation_alias=AliasChoices("old_str", "old_string", "old"),
    )
    new_str: str = Field(
        default="",
        max_length=500_000,
        validation_alias=AliasChoices("new_str", "new_string", "new"),
    )


class WriteFileArgs(BaseModel):
    """Совпадает с `write_file(path, content)` в file_ops.py."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    path: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices(
            "path", "filename", "file_path", "filepath",
            "target", "dest", "destination", "file",
        ),
    )
    content: str = Field(
        default="",
        max_length=2_000_000,
        validation_alias=AliasChoices(
            "content", "body", "text", "contents", "data", "source",
            "code", "file_content", "markdown", "md", "src",
        ),
    )


class ReplaceFileLinesArgs(BaseModel):
    """Совпадает с `replace_file_lines(path, start_line, end_line, content)`."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    path: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices("path", "filename", "file_path"),
    )
    start_line: int = Field(..., ge=1, le=10_000_000)
    end_line: int = Field(..., ge=1, le=10_000_000)
    content: str = Field(
        default="",
        max_length=500_000,
        validation_alias=AliasChoices("content", "new_content"),
    )


class InsertFileLinesArgs(BaseModel):
    """Совпадает с `insert_file_lines(path, after_line, content)`."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    path: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices("path", "filename", "file_path"),
    )
    after_line: int = Field(
        ...,
        ge=0,
        le=10_000_000,
        validation_alias=AliasChoices("after_line", "line_number"),
    )
    content: str = Field(..., max_length=500_000)


class StartBackgroundTaskArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    task: str = Field(
        ...,
        min_length=1,
        max_length=16_000,
        description="Краткая задача для фонового помощника (тест, curl, pytest на localhost)",
    )
    max_tool_rounds: int = Field(default=12, ge=1, le=40)


class GetBackgroundResultArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    job_id: str = Field(
        ...,
        min_length=4,
        max_length=120,
        validation_alias=AliasChoices("job_id", "token", "id"),
    )
    wait_seconds: int = Field(default=0, ge=0, le=3600)


class RunCommandArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    command: str = Field(..., min_length=1, max_length=8000, description="Одна команда; без интерактива")
    cwd: str = Field(default=".", max_length=2048)
    timeout_seconds: int = Field(default=120, ge=5, le=3600)


class WebSearchArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Короткий запрос; без дублирования с web_fetch",
        validation_alias=AliasChoices("query", "q", "search", "text"),
    )
    max_results: int = Field(default=8, ge=1, le=20)


class WebFetchArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    url: str = Field(..., min_length=8, max_length=2048, description="Полный URL одной страницы")


class DownloadFileArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    url: str = Field(..., min_length=8, max_length=2048,
                     description="http(s) URL to download")
    dest: str = Field(default="", max_length=1024,
                      description="Relative / absolute destination path")
    max_bytes: int = Field(default=0, ge=0, le=10_000_000_000)
    timeout_seconds: int = Field(default=60, ge=1, le=600)


class PlanToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    action: Literal["save", "load", "update", "clear"] = Field(..., description="Один action за вызов")
    title: str = Field(default="", max_length=500)
    steps_json: str = Field(default="[]", max_length=200_000, description="Для save: JSON-массив строк шагов")
    step_index: int = Field(default=0, ge=0, le=10_000)
    status: Literal["pending", "in_progress", "completed", "blocked"] = "pending"
    note: str = Field(default="", max_length=2000)


class LibraryContextArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    action: Literal["resolve", "docs", "search", "get_docs", "quick", "lookup"] = Field(...)
    library_name: str = Field(default="", max_length=200)
    library_id: str = Field(default="", max_length=500)
    query: str = Field(default="", max_length=8000)
    max_tokens: int = Field(default=4000, ge=100, le=32_000)


class ReasoningToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    action: Literal["think", "diff", "analyze", "show_diff", "analyze_code"] = Field(...)
    thought: str = Field(default="", max_length=50_000)
    path: str = Field(default="", max_length=2048)
    old_content: str = Field(default="", max_length=500_000)
    new_content: str = Field(default="", max_length=500_000)
    query: str = Field(default="", max_length=20_000)


class GitOpsArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    action: Literal["status", "log", "diff", "rollback_file", "rollback"] = Field(...)
    path: str = Field(default="", max_length=2048)
    limit: int = Field(default=15, ge=1, le=200)
    commit: str = Field(default="", max_length=128)


class FileVersionsToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    action: Literal["list", "rollback"] = Field(...)
    path: str = Field(default="", max_length=2048)
    limit: int = Field(default=20, ge=1, le=200)
    version_id: str = Field(default="", max_length=64)


class CodeFileToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    action: Literal["create", "append"] = Field(...)
    filepath: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices(
            "filepath", "path", "file", "file_path", "filename", "target",
        ),
    )
    language: str = Field(default="python", max_length=64)
    code: str = Field(
        default="",
        max_length=1_000_000,
        validation_alias=AliasChoices(
            "code", "content", "body", "source", "text", "file_content",
        ),
    )
    snippet: str = Field(
        default="",
        max_length=500_000,
        validation_alias=AliasChoices(
            "snippet", "fragment", "patch", "addition", "suffix",
        ),
    )


class OcrToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    action: Literal["soft", "medium", "strong"] = Field(...)
    path: str = Field(..., min_length=1, max_length=2048)


class GetFileLineCountArgs(BaseModel):
    """Совпадает с `get_file_line_count(path)`."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    path: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices("path", "filename", "file_path"),
    )


class AskUserArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    question: str = Field(..., min_length=1, max_length=8000)


class CodeInterpreterArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=500_000)


class RagSearchArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)


class HeadlessBrowserArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    action: str = Field(..., max_length=64)
    url: str = Field(default="", max_length=2048)
    selector: str = Field(default="body", max_length=1024)
    wait_ms: int = Field(default=3000, ge=0, le=120_000)
    output_path: str = Field(default="screenshot.png", max_length=1024)
    click_selector: str = Field(default="", max_length=1024)
    result_selector: str = Field(default="body", max_length=1024)
    js_expression: str = Field(default="", max_length=50_000)


class PlaywrightSyncArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    action: str = Field(..., max_length=64)
    url: str = Field(default="", max_length=2048)
    selector: str = Field(default="body", max_length=1024)
    wait_ms: int = Field(default=1500, ge=0, le=120_000)
    click_selector: str = Field(default="", max_length=1024)
    wait_after_ms: int = Field(default=2000, ge=0, le=120_000)
    field_selector: str = Field(default="", max_length=1024)
    fill_text: str = Field(default="", max_length=50_000)
    button_selector: str = Field(default="", max_length=1024)
    output_path: str = Field(default="pw_sync.png", max_length=1024)
    full_page: bool = False


# Registry: имя тула → модель
TOOL_ARG_MODELS: Dict[str, Type[BaseModel]] = {
    "read_file": ReadFileArgs,
    "read_file_lines": ReadFileLinesArgs,
    "list_files": ListFilesArgs,
    "start_background_task": StartBackgroundTaskArgs,
    "get_background_result": GetBackgroundResultArgs,
    "search_in_files": SearchInFilesArgs,
    "edit_file": EditFileArgs,
    "write_file": WriteFileArgs,
    "replace_file_lines": ReplaceFileLinesArgs,
    "insert_file_lines": InsertFileLinesArgs,
    "run_command": RunCommandArgs,
    "web_search": WebSearchArgs,
    "web_fetch": WebFetchArgs,
    "download_file": DownloadFileArgs,
    "plan_tool": PlanToolArgs,
    "library_context": LibraryContextArgs,
    "reasoning_tool": ReasoningToolArgs,
    "git_ops": GitOpsArgs,
    "file_versions_tool": FileVersionsToolArgs,
    "code_file_tool": CodeFileToolArgs,
    "ocr_tool": OcrToolArgs,
    "get_file_line_count": GetFileLineCountArgs,
    "ask_user": AskUserArgs,
    "code_interpreter": CodeInterpreterArgs,
    "rag_search": RagSearchArgs,
    "headless_browser": HeadlessBrowserArgs,
    "playwright_sync": PlaywrightSyncArgs,
}


_URL_LIKE_KEYS = ("url", "link", "href", "uri", "path")


_PLAN_ACTION_ALIASES = {
    "save_plan": "save",
    "create": "save",
    "create_plan": "save",
    "new": "save",
    "set": "save",
    "write": "save",
    "store": "save",
    "load_plan": "load",
    "get": "load",
    "read": "load",
    "show": "load",
    "status": "load",
    "update_plan": "update",
    "mark": "update",
    "set_status": "update",
    "progress": "update",
    "clear_plan": "clear",
    "reset": "clear",
    "delete": "clear",
    "remove": "clear",
}


def _coerce_common_arg_mistakes(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort rescue of tool calls where the model got the arg name wrong.

    Two scenarios handled here:
      * ``web_fetch`` called like ``write_file`` — ``{"path": ..., "content": ...}``
        — promote the URL-looking field to ``url`` so the schema accepts it.
      * ``plan_tool`` called with an aliased action (``save_plan`` instead of
        ``save``, ``mark`` instead of ``update`` …) — local models love to
        invent those. We remap to the canonical Literal values before schema
        validation so the call doesn't crash.
    """
    if not isinstance(args, dict):
        return args

    # ── write_file: non-string path/content, list-of-lines body ───────
    if tool_name == "write_file":
        p = dict(args)
        for key in ("path", "filename", "file_path", "filepath", "target",
                    "dest", "destination", "file"):
            v = p.get(key)
            if v is not None and not isinstance(v, str):
                p[key] = str(v)
        c = p.get("content")
        if isinstance(c, list):
            p["content"] = "\n".join(str(x) for x in c)
        elif c is not None and not isinstance(c, str):
            p["content"] = str(c)
        return p

    # ── code_file_tool: action synonyms, code vs snippet mix-ups ───────
    if tool_name == "code_file_tool":
        p = dict(args)
        act = str(p.get("action", "") or "").strip().lower()
        _cfa = {
            "write": "create", "new": "create", "overwrite": "create",
            "generate": "create", "touch": "create", "put": "create",
            "insert": "append", "add": "append", "extend": "append",
            "concat": "append", "merge": "append", "patch": "append",
            "update": "create",  # full-file rewrite → create path in tool
        }
        if act in _cfa:
            p["action"] = _cfa[act]
            act = p["action"]
        elif act and act not in ("create", "append"):
            has_snip = bool(str(p.get("snippet") or "").strip())
            has_code = bool(
                str(p.get("code") or p.get("content") or "").strip()
            )
            p["action"] = "append" if has_snip and not has_code else "create"
            act = p["action"]
        # Promote alternate bodies into ``code`` before field aliases run.
        if not str(p.get("code", "") or "").strip():
            for k in ("content", "body", "source", "text", "markdown",
                      "file_content", "src"):
                v = p.get(k)
                if isinstance(v, str) and v.strip():
                    p["code"] = v
                    break
                if isinstance(v, list):
                    p["code"] = "\n".join(str(x) for x in v)
                    break
        act = str(p.get("action", "") or "").strip().lower()
        if act == "create":
            # Many models put the whole file in ``snippet`` for action=create.
            if (not str(p.get("code", "") or "").strip()
                    and str(p.get("snippet", "") or "").strip()):
                p["code"] = str(p.pop("snippet", ""))
        elif act == "append":
            if not str(p.get("snippet", "") or "").strip():
                for k in ("code", "content", "body", "text", "fragment"):
                    v = p.get(k)
                    if isinstance(v, str) and v.strip():
                        p["snippet"] = v
                        break
        for fk in ("filepath", "path", "file", "file_path", "filename"):
            v = p.get(fk)
            if v is not None and not isinstance(v, str):
                p[fk] = str(v)
        return p

    # ── run_command: ``cmd`` / ``shell`` instead of ``command`` ────────
    if tool_name == "run_command":
        p = dict(args)
        if not str(p.get("command", "") or "").strip():
            for alt in ("cmd", "shell", "line", "script"):
                v = p.get(alt)
                if isinstance(v, str) and v.strip():
                    p["command"] = v.strip()
                    break
        return p

    # ── replace_file_lines / insert_file_lines: string line numbers ─────
    if tool_name in ("replace_file_lines", "insert_file_lines"):
        p = dict(args)
        for fld in ("start_line", "end_line", "after_line"):
            v = p.get(fld)
            if isinstance(v, str) and v.strip().lstrip("-").isdigit():
                try:
                    p[fld] = int(v.strip())
                except Exception:
                    pass
        return p

    if tool_name == "plan_tool":
        import json as _json
        patched = dict(args)

        # 1. Canonicalize ``action`` (always write back lowercased so
        #    ``"SAVE"`` → ``"save"`` passes the Literal check).
        act = str(patched.get("action", "") or "").strip().lower()
        if act in _PLAN_ACTION_ALIASES:
            act = _PLAN_ACTION_ALIASES[act]
        patched["action"] = act
        if act not in ("save", "load", "update", "clear"):
            # Infer action from payload if the model sent something totally
            # off like ``"plan"`` or ``"planning"`` — better than a schema
            # crash that the model will take as a dead-end.
            if patched.get("steps_json") or patched.get("steps") or patched.get("items"):
                patched["action"] = "save"
            elif patched.get("step_index") is not None and patched.get("status"):
                patched["action"] = "update"
            else:
                patched["action"] = "load"
            act = patched["action"]

        # 2. Accept ``steps`` / ``items`` / ``tasks`` (native list) instead
        #    of ``steps_json`` (str). Coerce into a JSON string before we
        #    hand it to Pydantic.
        for list_key in ("steps", "items", "tasks", "plan"):
            if list_key in patched and "steps_json" not in patched:
                val = patched[list_key]
                if isinstance(val, list):
                    try:
                        patched["steps_json"] = _json.dumps([str(x) for x in val],
                                                            ensure_ascii=False)
                    except Exception:
                        patched["steps_json"] = "[]"
                elif isinstance(val, str) and val.strip().startswith("["):
                    patched["steps_json"] = val
                patched.pop(list_key, None)

        # 3. ``steps_json`` must be a string; if the model stuffed a list
        #    in there directly, re-serialize.
        sj = patched.get("steps_json")
        if isinstance(sj, list):
            try:
                patched["steps_json"] = _json.dumps([str(x) for x in sj],
                                                    ensure_ascii=False)
            except Exception:
                patched["steps_json"] = "[]"

        # 4. Status synonyms so ``"done"`` / ``"in progress"`` validate.
        raw_status = str(patched.get("status", "") or "")
        if raw_status:
            st = raw_status.strip().lower().replace(" ", "_").replace("-", "_")
            status_aliases = {
                "todo": "pending", "open": "pending", "new": "pending",
                "pending": "pending",
                "doing": "in_progress", "in_progress": "in_progress",
                "progress": "in_progress", "wip": "in_progress",
                "active": "in_progress", "running": "in_progress",
                "done": "completed", "finished": "completed", "ok": "completed",
                "complete": "completed", "completed": "completed",
                "blocked": "blocked", "stuck": "blocked", "failed": "blocked",
                "skipped": "blocked", "error": "blocked",
            }
            patched["status"] = status_aliases.get(st, "pending")

        # 5. Gracefully truncate oversize strings the schema would reject.
        if isinstance(patched.get("title"), str) and len(patched["title"]) > 500:
            patched["title"] = patched["title"][:500]
        if isinstance(patched.get("note"), str) and len(patched["note"]) > 2000:
            patched["note"] = patched["note"][:2000]
        if isinstance(patched.get("step_index"), str):
            try:
                patched["step_index"] = int(patched["step_index"])
            except Exception:
                patched["step_index"] = 0
        try:
            patched["step_index"] = max(0, min(int(patched.get("step_index", 0)), 10_000))
        except Exception:
            patched["step_index"] = 0

        return patched

    if tool_name == "web_fetch" and "url" not in args:
        candidate = ""
        for k in _URL_LIKE_KEYS:
            v = args.get(k)
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                candidate = v
                break
        if not candidate:
            for v in args.values():
                if isinstance(v, str) and v.lstrip().startswith(("http://", "https://")):
                    candidate = v.strip().split()[0]
                    break
        if candidate:
            patched = {k: v for k, v in args.items()
                       if k not in _URL_LIKE_KEYS and k != "content"}
            patched["url"] = candidate
            return patched

    return args


def validate_tool_arguments(tool_name: str, args: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """Возвращает (нормализованные аргументы, текст ошибки или None)."""
    if not isinstance(args, dict):
        return {}, "args_must_be_object"
    args = _coerce_common_arg_mistakes(tool_name, args)
    model_cls = TOOL_ARG_MODELS.get(tool_name)
    if model_cls is None:
        return dict(args), None
    try:
        m = model_cls.model_validate(args)
        return m.model_dump(exclude_none=True), None
    except Exception as e:
        return args, f"validation: {type(e).__name__}: {e}"
