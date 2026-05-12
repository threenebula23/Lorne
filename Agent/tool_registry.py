"""Реестр инструментов Lorne: сборка списка тулов для LLM и карты dispatch.

Точка расширения для новых тулов — см. wiki/developer/ADDING_TOOLS.md.
"""
from typing import Any, Dict, List

from langchain_core.tools import BaseTool

try:
    from .tools.planning_tool import save_plan, load_plan, update_plan, clear_plan
    from .tools.versioning_tool import list_file_versions, rollback_file
    from .tools.office_document_tool import docx_document_advanced_ops, pdf_styled_document_create
    from .tools.qa_tool import run_package_script
    from .tools import (
        read_file, read_file_lines, list_files, edit_file, search_in_files, find_in_file, write_file,
        replace_file_lines, insert_file_lines,
        get_file_line_count, run_command, download_file, create_pdf, ask_user,
        web_search, web_fetch,
        office_document_read,
        code_interpreter,
        load_custom_tools, list_custom_tools, add_custom_tool,
        remove_custom_tool, get_custom_tools_prompt, reload_custom_tools,
    )
    from .tools.compact_tools import (
        plan_tool,
        docx_write_tool,
        docxedit_tool,
        ocr_tool,
        code_file_tool,
        git_ops,
        library_context,
        reasoning_tool,
        headless_browser,
        playwright_sync,
        file_versions_tool,
        project_brain_tool,
    )
    from .rag import get_rag_tool
    from .tools.parallel_helper_tool import start_background_task, get_background_result
except ImportError:
    from Agent.tools.planning_tool import save_plan, load_plan, update_plan, clear_plan
    from Agent.tools.versioning_tool import list_file_versions, rollback_file
    from Agent.tools.office_document_tool import docx_document_advanced_ops, pdf_styled_document_create
    from Agent.tools.qa_tool import run_package_script
    from Agent.tools import (
        read_file, read_file_lines, list_files, edit_file, search_in_files, find_in_file, write_file,
        replace_file_lines, insert_file_lines,
        get_file_line_count, run_command, download_file, create_pdf, ask_user,
        web_search, web_fetch,
        office_document_read,
        code_interpreter,
        load_custom_tools, list_custom_tools, add_custom_tool,
        remove_custom_tool, get_custom_tools_prompt, reload_custom_tools,
    )
    from Agent.tools.compact_tools import (
        plan_tool,
        docx_write_tool,
        docxedit_tool,
        ocr_tool,
        code_file_tool,
        git_ops,
        library_context,
        reasoning_tool,
        headless_browser,
        playwright_sync,
        file_versions_tool,
        project_brain_tool,
    )
    from Agent.rag import get_rag_tool
    from Agent.tools.parallel_helper_tool import start_background_task, get_background_result

try:
    from .llm_provider import supports_parallel_tool_calls_param
except ImportError:
    from Agent.llm_provider import supports_parallel_tool_calls_param

try:
    from .tools.git_tool import git_log  # noqa: F401
    _HAS_GIT_TOOLS = True
except ImportError:
    _HAS_GIT_TOOLS = False

__all__ = [
    "build_tools", "build_tool_map", "bind_tools_safe", "reload_tools",
    "set_tool_session_prefs",
    "load_custom_tools", "list_custom_tools", "add_custom_tool",
    "remove_custom_tool", "get_custom_tools_prompt", "reload_custom_tools",
    "save_plan", "load_plan", "update_plan", "clear_plan",
    "list_file_versions", "rollback_file", "list_files",
    "plan_tool",
]

_base_tools: List[Any] = [
    read_file, read_file_lines, list_files, edit_file, write_file,
    replace_file_lines, insert_file_lines,
    get_file_line_count,
    code_file_tool,
    plan_tool,
    search_in_files, find_in_file, run_command, run_package_script, download_file, create_pdf, ask_user,
    web_search, web_fetch,
    start_background_task, get_background_result,
    ocr_tool,
    office_document_read,
    docx_write_tool,
    docx_document_advanced_ops,
    docxedit_tool,
    pdf_styled_document_create,
    reasoning_tool,
    code_interpreter,
    get_rag_tool(),
    project_brain_tool,
]

if _HAS_GIT_TOOLS:
    _base_tools.append(git_ops)

_base_tools.append(library_context)

_base_tools.append(file_versions_tool)

try:
    from .tools.browser_tool import browser_get_text  # noqa: F401
    _HAS_BROWSER_TOOLS = True
except ImportError:
    _HAS_BROWSER_TOOLS = False

try:
    from .tools.playwright_sync_tool import playwright_sync_page_text  # noqa: F401
    _HAS_PLAYWRIGHT_SYNC = True
except ImportError:
    _HAS_PLAYWRIGHT_SYNC = False


_browser_node_tools: List[Any] = []
if _HAS_BROWSER_TOOLS:
    _browser_node_tools.append(headless_browser)

_playwright_python_tools: List[Any] = []
if _HAS_PLAYWRIGHT_SYNC:
    _playwright_python_tools.append(playwright_sync)

_tool_session_flags: Dict[str, bool] = {
    "agent_mode": False,
    "ask_mode": False,
    "playwright_python": False,
    "browser_tools": True,
    "custom_tools": True,
}

_ASK_EXCLUDED_TOOL_NAMES = frozenset({
    "edit_file", "write_file", "replace_file_lines", "insert_file_lines",
    "code_file_tool", "docx_write_tool", "docxedit_tool", "docx_document_advanced_ops",
    "pdf_styled_document_create", "git_ops", "download_file", "run_command",
    "start_background_task", "get_background_result", "run_package_script",
    "create_pdf", "file_versions_tool", "code_interpreter",
    "project_brain_tool",
})


# Names of the "custom" tools that users can disable wholesale from the
# Agents settings screen. Removing them shrinks the tool surface for cheap
# local models and prevents accidental RAG / planning calls in simple chats.
_CUSTOM_TOOL_NAMES = frozenset({
    "rag_search",
    "plan_tool",
    "reasoning_tool",
    "code_interpreter",
    "library_context",
    "file_versions_tool",
    "project_brain_tool",
})


def set_tool_session_prefs(
    *,
    agent_mode: bool = False,
    ask_mode: bool = False,
    playwright_python: bool = False,
    browser_tools: bool = True,
    custom_tools: bool = True,
) -> None:
    _tool_session_flags["agent_mode"] = bool(agent_mode)
    _tool_session_flags["ask_mode"] = bool(ask_mode)
    _tool_session_flags["playwright_python"] = bool(playwright_python)
    _tool_session_flags["browser_tools"] = bool(browser_tools)
    _tool_session_flags["custom_tools"] = bool(custom_tools)


def _strip_custom_tools(tools: List[Any]) -> List[Any]:
    return [t for t in tools if (getattr(t, "name", "") or "") not in _CUSTOM_TOOL_NAMES]


def build_tools(
    agent_mode: bool = False,
    ask_mode: bool = False,
    playwright_python: bool = False,
    browser_tools: bool = True,
    custom_tools: bool = True,
) -> tuple[List[Any], Any]:
    """Return ``(tools, custom_list)`` for the session; flags control browser / ask."""
    custom = load_custom_tools() if custom_tools else []
    base = list(_base_tools) if custom_tools else _strip_custom_tools(_base_tools)
    all_tools = base + list(custom)
    if ask_mode:
        all_tools = [
            t for t in all_tools
            if (getattr(t, "name", "") or "") not in _ASK_EXCLUDED_TOOL_NAMES
        ]
    if agent_mode and browser_tools and _browser_node_tools:
        all_tools.extend(_browser_node_tools)
    if agent_mode and playwright_python and _playwright_python_tools:
        all_tools.extend(_playwright_python_tools)
    return all_tools, custom


def get_agent_mode_tools() -> List[Any]:
    out: List[Any] = []
    out.extend(_browser_node_tools)
    out.extend(_playwright_python_tools)
    return out


def build_tool_map(tools: List[Any]) -> Dict[str, BaseTool]:
    tool_map: Dict[str, BaseTool] = {}
    for t in tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", None)
        if name:
            tool_map[str(name)] = t
    try:
        try:
            from .message_utils import register_known_tool_names
        except ImportError:
            from Agent.message_utils import register_known_tool_names
        register_known_tool_names(tool_map.keys())
    except Exception:
        pass
    return tool_map


def bind_tools_safe(llm_obj: Any, model_name: str, tools: List[Any],
                    force_no_parallel: bool = False) -> Any:
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


def reload_tools(current_tools: List[Any]) -> List[Any]:
    custom_new = reload_custom_tools()
    am = _tool_session_flags.get("agent_mode", False)
    ask = _tool_session_flags.get("ask_mode", False)
    pw = _tool_session_flags.get("playwright_python", False)
    bw = _tool_session_flags.get("browser_tools", True)
    ct = _tool_session_flags.get("custom_tools", True)
    fresh, _ = build_tools(
        agent_mode=am, ask_mode=ask, playwright_python=pw, browser_tools=bw, custom_tools=ct,
    )
    current_tools.clear()
    current_tools.extend(fresh)
    return custom_new
