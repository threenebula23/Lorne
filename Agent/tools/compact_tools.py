"""Компактные мульти-тулы: одна схема вместо нескольких — меньше токенов на bind_tools.

Логика делегирует существующим реализациям (planning_tool, office, docxedit, ocr, git, context7, code_gen, browser, playwright).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.tools import tool

try:
    from .planning_tool import save_plan, load_plan, update_plan, clear_plan
    from .office_document_tool import (
        docx_document_create,
        docx_document_append_paragraphs,
        docx_document_patch_paragraphs,
    )
    from .docxedit_tools import (
        docxedit_replace_keep_format,
        docxedit_replace_up_to_paragraph,
        docxedit_find_line,
        docxedit_table_cell_append,
        docxedit_table_font_size,
    )
    from .ocr_tool import ocr_read_file_soft, ocr_read_image_medium, ocr_read_photo_strong
    from .code_gen import create_code_file, append_code_snippet
except ImportError:
    from Agent.tools.planning_tool import save_plan, load_plan, update_plan, clear_plan
    from Agent.tools.office_document_tool import (
        docx_document_create,
        docx_document_append_paragraphs,
        docx_document_patch_paragraphs,
    )
    from Agent.tools.docxedit_tools import (
        docxedit_replace_keep_format,
        docxedit_replace_up_to_paragraph,
        docxedit_find_line,
        docxedit_table_cell_append,
        docxedit_table_font_size,
    )
    from Agent.tools.ocr_tool import ocr_read_file_soft, ocr_read_image_medium, ocr_read_photo_strong
    from Agent.tools.code_gen import create_code_file, append_code_snippet


def _plan_steps_from_json(steps_json: str) -> List[str]:
    data = json.loads(steps_json)
    if not isinstance(data, list):
        raise ValueError("steps_json: ожидается JSON-массив строк")
    return [str(x) for x in data]


@tool
def plan_tool(
    action: str,
    title: str = "",
    steps_json: str = "",
    step_index: int = 0,
    status: str = "pending",
    note: str = "",
) -> Dict[str, Any]:
    """План задачи (один тул вместо save/load/update/clear_plan).

    action:
    - `save` — title, steps_json (JSON-массив строк шагов).
    - `load` — без доп. полей.
    - `update` — step_index, status (pending|in_progress|completed|blocked), note (опц.).
    - `clear` — очистить план (в CLI может запросить подтверждение).
    """
    a = (action or "").strip().lower()
    if a == "save":
        if not steps_json.strip():
            return {"ok": False, "error": "steps_json_required"}
        steps = _plan_steps_from_json(steps_json)
        out = save_plan.invoke({"title": title or "План", "steps": steps})
        return {**out, "_plan_action": "save_plan"}
    if a == "load":
        out = load_plan.invoke({})
        return {**out, "_plan_action": "load_plan"}
    if a == "update":
        out = update_plan.invoke({"step_index": step_index, "status": status, "note": note})
        return {**out, "_plan_action": "update_plan"}
    if a == "clear":
        out = clear_plan.invoke({})
        return {**out, "_plan_action": "clear_plan"}
    return {"ok": False, "error": "bad_action", "hint": "save|load|update|clear"}


@tool
def docx_write_tool(
    action: str,
    file_path: str,
    data_json: str,
) -> Dict[str, Any]:
    """Создание/дозапись/патч .docx одним тулом (вместо трёх отдельных).

    action:
    - `create` — data_json как paragraphs_json у docx_document_create.
    - `append` — data_json как paragraphs_json у append_paragraphs.
    - `patch` — data_json как patches_json у patch_paragraphs.
    """
    a = (action or "").strip().lower()
    if a == "create":
        return docx_document_create.invoke({"file_path": file_path, "paragraphs_json": data_json})
    if a == "append":
        return docx_document_append_paragraphs.invoke({"file_path": file_path, "paragraphs_json": data_json})
    if a == "patch":
        return docx_document_patch_paragraphs.invoke({"file_path": file_path, "patches_json": data_json})
    return {"error": "bad_action", "hint": "create|append|patch"}


@tool
def docxedit_tool(
    action: str,
    file_path: str,
    old_string: str = "",
    new_string: str = "",
    include_tables: bool = True,
    paragraph_number: int = 1,
    search_text: str = "",
    table_index: int = 0,
    row_num: int = 1,
    column_num: int = 1,
    font_size: int = 12,
) -> Dict[str, Any]:
    """Правки .docx с сохранением формата (docxedit) одним тулом.

    action:
    - `replace` — old_string, new_string, include_tables.
    - `replace_limited` — old_string, new_string, paragraph_number, include_tables.
    - `find_line` — search_text.
    - `table_cell` — table_index, row_num, column_num, new_string.
    - `table_font` — table_index, font_size.
    """
    a = (action or "").strip().lower()
    if a == "replace":
        return docxedit_replace_keep_format.invoke(
            {"file_path": file_path, "old_string": old_string, "new_string": new_string, "include_tables": include_tables}
        )
    if a in ("replace_limited", "replace_up_to_paragraph"):
        return docxedit_replace_up_to_paragraph.invoke(
            {
                "file_path": file_path,
                "old_string": old_string,
                "new_string": new_string,
                "paragraph_number": paragraph_number,
                "include_tables": include_tables,
            }
        )
    if a in ("find_line", "find"):
        return docxedit_find_line.invoke({"file_path": file_path, "search_text": search_text or old_string})
    if a in ("table_cell", "cell"):
        return docxedit_table_cell_append.invoke(
            {
                "file_path": file_path,
                "table_index": table_index,
                "row_num": row_num,
                "column_num": column_num,
                "new_string": new_string,
            }
        )
    if a in ("table_font", "table_font_size"):
        return docxedit_table_font_size.invoke(
            {"file_path": file_path, "table_index": table_index, "font_size": font_size}
        )
    return {"error": "bad_action", "hint": "replace|replace_limited|find_line|table_cell|table_font"}


@tool
def ocr_tool(
    action: str,
    path: str,
    max_chars: int = 60_000,
    max_pdf_pages: int = 30,
    max_side: int = 2400,
) -> Dict[str, Any]:
    """OCR/чтение файла или изображения одним тулом.

    action:
    - `soft` — path к .txt/.md/.py/.pdf (текстовый слой); max_pdf_pages, max_chars.
    - `medium` — path к изображению (скрин, UI); max_side, max_chars.
    - `strong` — path к фото; max_side, max_chars.
    """
    a = (action or "").strip().lower()
    if a == "soft":
        return ocr_read_file_soft.invoke(
            {"file_path": path, "max_chars": max_chars, "max_pdf_pages": max_pdf_pages}
        )
    if a == "medium":
        return ocr_read_image_medium.invoke(
            {"image_path": path, "max_side": max_side, "max_chars": max_chars}
        )
    if a == "strong":
        return ocr_read_photo_strong.invoke(
            {"image_path": path, "max_side": max_side, "max_chars": max_chars}
        )
    return {"error": "bad_action", "hint": "soft|medium|strong"}


@tool
def code_file_tool(
    action: str,
    filepath: str,
    language: str = "python",
    code: str = "",
    snippet: str = "",
) -> Dict[str, Any]:
    """Создать файл с кодом или дописать фрагмент.

    action: `create` — filepath, language, code; `append` — filepath, snippet, language (опц.).
    """
    a = (action or "").strip().lower()
    if a == "create":
        return create_code_file.invoke({"filepath": filepath, "language": language, "code": code})
    if a == "append":
        return append_code_snippet.invoke({"filepath": filepath, "snippet": snippet, "language": language})
    return {"error": "bad_action", "hint": "create|append"}


def _git_invoke():
    try:
        from .git_tool import git_log, git_diff, git_rollback_file, git_status
        return git_log, git_diff, git_rollback_file, git_status
    except ImportError:
        from Agent.tools.git_tool import git_log, git_diff, git_rollback_file, git_status
        return git_log, git_diff, git_rollback_file, git_status


@tool
def git_ops(
    action: str,
    path: str = "",
    limit: int = 15,
    commit: str = "",
) -> Dict[str, Any]:
    """Git одним тулом: status | log | diff | rollback_file.

    - `status` — без полей.
    - `log` — path (фильтр), limit.
    - `diff` — commit (пусто = незакоммиченное).
    - `rollback_file` — path (файл), commit (опц.).
    """
    git_log, git_diff, git_rollback_file, git_status = _git_invoke()
    a = (action or "").strip().lower()
    if a == "status":
        return git_status.invoke({})
    if a == "log":
        return git_log.invoke({"path": path, "limit": limit})
    if a == "diff":
        return git_diff.invoke({"commit": commit})
    if a in ("rollback_file", "rollback"):
        if not path.strip():
            return {"error": "path_required"}
        return git_rollback_file.invoke({"path": path, "commit": commit})
    return {"error": "bad_action", "hint": "status|log|diff|rollback_file"}


def _c7_invoke():
    try:
        from .context7_tool import resolve_library, get_library_docs, get_documentation
        return resolve_library, get_library_docs, get_documentation
    except ImportError:
        from Agent.tools.context7_tool import resolve_library, get_library_docs, get_documentation
        return resolve_library, get_library_docs, get_documentation


@tool
def library_context(
    action: str,
    library_name: str = "",
    library_id: str = "",
    query: str = "",
    max_tokens: int = 4000,
) -> Dict[str, Any]:
    """Документация библиотек (Context7 + fallback) и быстрый поиск — **единый тул** вместо resolve + get_library_docs + get_documentation.

    action:
    - `resolve` — найти пакет по имени: **library_name** (например react).
    - `docs` — выборка по Context7: **library_id** (из resolve), **query**, max_tokens.
    - `search` — быстрый сценарий как бывший **get_documentation**: **query** обязателен; **library_name** опционально
      (подсказка библиотеки). С API-ключом Context7 — resolve+context; иначе DDG. Для «общего веба» по ссылкам используй **web_fetch**.
    """
    resolve_library, get_library_docs, get_documentation = _c7_invoke()
    a = (action or "").strip().lower()
    if a == "resolve":
        if not library_name.strip():
            return {"error": "library_name_required"}
        return resolve_library.invoke({"library_name": library_name})
    if a in ("docs", "get_docs"):
        if not library_id.strip():
            return {"error": "library_id_required"}
        return get_library_docs.invoke(
            {"library_id": library_id, "query": query or "overview", "max_tokens": max_tokens}
        )
    if a in ("search", "quick", "lookup"):
        if not (query or "").strip():
            return {"error": "query_required", "hint": "Для search нужен query; library_name опционально."}
        return get_documentation.invoke({"query": query.strip(), "library": (library_name or "").strip()})
    return {"error": "bad_action", "hint": "resolve|docs|search"}


def _browser_invoke():
    try:
        from .browser_tool import browser_get_text, browser_screenshot, browser_click_and_get, browser_evaluate
        return browser_get_text, browser_screenshot, browser_click_and_get, browser_evaluate
    except ImportError:
        from Agent.tools.browser_tool import browser_get_text, browser_screenshot, browser_click_and_get, browser_evaluate
        return browser_get_text, browser_screenshot, browser_click_and_get, browser_evaluate


@tool
def headless_browser(
    action: str,
    url: str = "",
    selector: str = "body",
    wait_ms: int = 3000,
    output_path: str = "screenshot.png",
    click_selector: str = "",
    result_selector: str = "body",
    js_expression: str = "",
) -> Dict[str, Any]:
    """Headless Chromium (Node) одним тулом.

    action:
    - `get_text` — url, selector, wait_ms.
    - `screenshot` — url, output_path, wait_ms.
    - `click_and_get` — url, click_selector, result_selector (куда читать текст после клика), wait_ms.
    - `evaluate` — url, js_expression.
    """
    btext, bshot, bclick, beval = _browser_invoke()
    a = (action or "").strip().lower().replace("-", "_")
    if a == "get_text":
        return btext.invoke({"url": url, "selector": selector, "wait_ms": wait_ms})
    if a in ("screenshot", "shot"):
        return bshot.invoke({"url": url, "output_path": output_path, "wait_ms": wait_ms})
    if a in ("click_and_get", "click"):
        return bclick.invoke(
            {
                "url": url,
                "click_selector": click_selector,
                "result_selector": result_selector or "body",
                "wait_ms": wait_ms,
            }
        )
    if a in ("evaluate", "eval_js"):
        return beval.invoke({"url": url, "js_expression": js_expression})
    return {"error": "bad_action", "hint": "get_text|screenshot|click_and_get|evaluate"}


def _pw_invoke():
    try:
        from .playwright_sync_tool import (
            playwright_sync_page_text,
            playwright_sync_click,
            playwright_sync_fill_and_optional_click,
            playwright_sync_screenshot,
        )
        return (
            playwright_sync_page_text,
            playwright_sync_click,
            playwright_sync_fill_and_optional_click,
            playwright_sync_screenshot,
        )
    except ImportError:
        from Agent.tools.playwright_sync_tool import (
            playwright_sync_page_text,
            playwright_sync_click,
            playwright_sync_fill_and_optional_click,
            playwright_sync_screenshot,
        )
        return (
            playwright_sync_page_text,
            playwright_sync_click,
            playwright_sync_fill_and_optional_click,
            playwright_sync_screenshot,
        )


@tool
def playwright_sync(
    action: str,
    url: str = "",
    selector: str = "body",
    wait_ms: int = 1500,
    click_selector: str = "",
    wait_after_ms: int = 2000,
    field_selector: str = "",
    fill_text: str = "",
    button_selector: str = "",
    output_path: str = "pw_sync.png",
    full_page: bool = False,
) -> Dict[str, Any]:
    """Python Playwright (sync) одним тулом — только если включён в настройках Agent.

    action:
    - `page_text` — url, selector, wait_ms.
    - `click` — url, click_selector (= selector для клика), wait_after_ms.
    - `fill_submit` — url, field_selector, fill_text, button_selector (опц.).
    - `screenshot` — url, output_path, full_page.
    """
    pt, pc, pf, ps = _pw_invoke()
    a = (action or "").strip().lower()
    if a in ("page_text", "text"):
        return pt.invoke({"url": url, "selector": selector, "wait_ms": wait_ms})
    if a == "click":
        sel = click_selector or selector
        return pc.invoke({"url": url, "selector": sel, "wait_after_ms": wait_after_ms})
    if a in ("fill_submit", "fill"):
        return pf.invoke(
            {
                "url": url,
                "field_selector": field_selector,
                "text": fill_text,
                "button_selector": button_selector,
            }
        )
    if a in ("screenshot", "shot"):
        return ps.invoke({"url": url, "output_path": output_path, "full_page": full_page})
    return {"error": "bad_action", "hint": "page_text|click|fill_submit|screenshot"}


def _reasoning_invoke():
    try:
        from .thinking_tool import think, show_diff, analyze_code
        return think, show_diff, analyze_code
    except ImportError:
        from Agent.tools.thinking_tool import think, show_diff, analyze_code
        return think, show_diff, analyze_code


@tool
def reasoning_tool(
    action: str,
    thought: str = "",
    path: str = "",
    old_content: str = "",
    new_content: str = "",
    query: str = "",
) -> Dict[str, Any]:
    """Рассуждения и анализ одним тулом (вместо think / show_diff / analyze_code).

    action:
    - `think` — **thought** (короткая запись плана/гипотезы).
    - `diff` — **path**, **old_content**, **new_content** (unified diff, для предпросмотра перед edit).
    - `analyze` — **path**, **query** (RAG + заголовок файла).
    """
    think, show_diff, analyze_code = _reasoning_invoke()
    a = (action or "").strip().lower()
    if a == "think":
        if not (thought or "").strip():
            return {"error": "thought_required"}
        return think.invoke({"thought": thought})
    if a in ("diff", "show_diff"):
        if not path.strip():
            return {"error": "path_required"}
        return show_diff.invoke({"path": path, "old_content": old_content, "new_content": new_content})
    if a in ("analyze", "analyze_code"):
        if not path.strip() or not (query or "").strip():
            return {"error": "path_and_query_required"}
        return analyze_code.invoke({"path": path, "query": query})
    return {"error": "bad_action", "hint": "think|diff|analyze"}


@tool
def file_versions_tool(
    action: str,
    path: str = "",
    limit: int = 20,
    version_id: str = "",
) -> Dict[str, Any]:
    """Версии файла: list | rollback."""
    try:
        from .versioning_tool import list_file_versions, rollback_file
    except ImportError:
        from Agent.tools.versioning_tool import list_file_versions, rollback_file
    a = (action or "").strip().lower()
    if a == "list":
        return list_file_versions.invoke({"path": path, "limit": limit})
    if a == "rollback":
        return rollback_file.invoke({"path": path, "version_id": version_id})
    return {"error": "bad_action", "hint": "list|rollback"}
