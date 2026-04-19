"""Pydantic-схемы аргументов инструментов: валидация, сжатие лишних полей, подсказки модели.

Используется в graph_runner перед invoke — снижает число «битых» вызовов без потери выразительности.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Tuple, Type

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# ─── Базовые модели по частым тулам ─────────────────────────────────


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    # В коде тула параметр называется `filename`; модели часто шлют `path`.
    filename: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices("filename", "path", "file_path"),
    )
    encoding: str = Field(default="utf-8", max_length=32)
    offset: int = Field(default=0, ge=0, le=500_000, description="Номер начальной строки (0-based)")
    limit: int = Field(default=0, ge=0, le=5000, description="Сколько строк; 0 = весь файл")


class ListFilesArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    path: str = Field(..., min_length=1, max_length=2048)
    recursive: bool = False
    pattern: str = Field(default="*", max_length=256)


class SearchInFilesArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    directory: str = Field(..., min_length=1, max_length=2048)
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
        validation_alias=AliasChoices("path", "filename", "file_path"),
    )
    content: str = Field(default="", max_length=2_000_000)


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


class RunCommandArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    command: str = Field(..., min_length=1, max_length=8000, description="Одна команда; без интерактива")
    cwd: str = Field(default=".", max_length=2048)
    timeout_seconds: int = Field(default=120, ge=5, le=3600)


class WebSearchArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    query: str = Field(..., min_length=1, max_length=500, description="Короткий запрос; без дублирования с web_fetch")
    max_results: int = Field(default=8, ge=1, le=20)


class WebFetchArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    url: str = Field(..., min_length=8, max_length=2048, description="Полный URL одной страницы")


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
    filepath: str = Field(..., min_length=1, max_length=2048)
    language: str = Field(default="python", max_length=64)
    code: str = Field(default="", max_length=1_000_000)
    snippet: str = Field(default="", max_length=500_000)


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
    "list_files": ListFilesArgs,
    "search_in_files": SearchInFilesArgs,
    "edit_file": EditFileArgs,
    "write_file": WriteFileArgs,
    "replace_file_lines": ReplaceFileLinesArgs,
    "insert_file_lines": InsertFileLinesArgs,
    "run_command": RunCommandArgs,
    "web_search": WebSearchArgs,
    "web_fetch": WebFetchArgs,
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


def validate_tool_arguments(tool_name: str, args: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """Возвращает (нормализованные аргументы, текст ошибки или None)."""
    if not isinstance(args, dict):
        return {}, "args_must_be_object"
    model_cls = TOOL_ARG_MODELS.get(tool_name)
    if model_cls is None:
        return dict(args), None
    try:
        m = model_cls.model_validate(args)
        return m.model_dump(exclude_none=True), None
    except Exception as e:
        return args, f"validation: {type(e).__name__}: {e}"
