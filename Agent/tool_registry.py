"""Tool registry: builds and manages the tool list and dispatch map."""
from typing import Any, Dict, List

from langchain_core.tools import BaseTool

try:
    from .tools.planning_tool import save_plan, load_plan, update_plan, clear_plan
    from .tools.versioning_tool import list_file_versions, rollback_file
    from .tools.office_document_tool import docx_document_advanced_ops, pdf_styled_document_create
    from .tools import (
        read_file, list_files, edit_file, search_in_files, write_file,
        replace_file_lines, insert_file_lines,
        get_file_line_count, run_command, create_pdf, ask_user,
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
    )
    from .rag import get_rag_tool
except ImportError:
    from Agent.tools.planning_tool import save_plan, load_plan, update_plan, clear_plan
    from Agent.tools.versioning_tool import list_file_versions, rollback_file
    from Agent.tools.office_document_tool import docx_document_advanced_ops, pdf_styled_document_create
    from Agent.tools import (
        read_file, list_files, edit_file, search_in_files, write_file,
        replace_file_lines, insert_file_lines,
        get_file_line_count, run_command, create_pdf, ask_user,
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
    )
    from Agent.rag import get_rag_tool

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
    read_file, list_files, edit_file, write_file,
    replace_file_lines, insert_file_lines,
    get_file_line_count,
    code_file_tool,
    plan_tool,
    search_in_files, run_command, create_pdf, ask_user,
    web_search, web_fetch,
    ocr_tool,
    office_document_read,
    docx_write_tool,
    docx_document_advanced_ops,
    docxedit_tool,
    pdf_styled_document_create,
    reasoning_tool,
    code_interpreter,
    get_rag_tool(),
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

_tool_session_flags: Dict[str, bool] = {"agent_mode": False, "playwright_python": False}


def set_tool_session_prefs(*, agent_mode: bool = False, playwright_python: bool = False) -> None:
    _tool_session_flags["agent_mode"] = bool(agent_mode)
    _tool_session_flags["playwright_python"] = bool(playwright_python)


def build_tools(
    agent_mode: bool = False,
    playwright_python: bool = False,
) -> tuple[List[Any], Any]:
    custom = load_custom_tools()
    all_tools = list(_base_tools) + list(custom)
    if agent_mode and _browser_node_tools:
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
    pw = _tool_session_flags.get("playwright_python", False)
    fresh, _ = build_tools(agent_mode=am, playwright_python=pw)
    current_tools.clear()
    current_tools.extend(fresh)
    return custom_new
