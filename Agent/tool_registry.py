"""Tool registry: builds and manages the tool list and dispatch map."""
from typing import Any, Dict, List

from langchain_core.tools import BaseTool

try:
    from .tools import (
        read_file, list_files, edit_file, search_in_files, write_file,
        get_file_line_count, run_command, create_pdf, ask_user,
        create_code_file, append_code_snippet,
        save_plan, load_plan, update_plan, clear_plan,
        list_file_versions, rollback_file,
        web_search, web_fetch, get_documentation, code_interpreter,
        load_custom_tools, list_custom_tools, add_custom_tool,
        remove_custom_tool, get_custom_tools_prompt, reload_custom_tools,
    )
    from .tools.web_tool import web_search_and_read
    from .rag import get_rag_tool
except ImportError:
    from Agent.tools import (
        read_file, list_files, edit_file, search_in_files, write_file,
        get_file_line_count, run_command, create_pdf, ask_user,
        create_code_file, append_code_snippet,
        save_plan, load_plan, update_plan, clear_plan,
        list_file_versions, rollback_file,
        web_search, web_fetch, get_documentation, code_interpreter,
        load_custom_tools, list_custom_tools, add_custom_tool,
        remove_custom_tool, get_custom_tools_prompt, reload_custom_tools,
    )
    from Agent.tools.web_tool import web_search_and_read
    from Agent.rag import get_rag_tool

try:
    from .llm_provider import supports_parallel_tool_calls_param
except ImportError:
    from Agent.llm_provider import supports_parallel_tool_calls_param

try:
    from .tools.git_tool import git_log, git_diff, git_rollback_file, git_status
    _HAS_GIT_TOOLS = True
except ImportError:
    _HAS_GIT_TOOLS = False

try:
    from .tools.context7_tool import resolve_library, get_library_docs
    _HAS_C7_TOOLS = True
except ImportError:
    _HAS_C7_TOOLS = False


# Re-export for command_router and other modules
__all__ = [
    "build_tools", "build_tool_map", "bind_tools_safe", "reload_tools",
    "load_custom_tools", "list_custom_tools", "add_custom_tool",
    "remove_custom_tool", "get_custom_tools_prompt", "reload_custom_tools",
    "save_plan", "load_plan", "update_plan", "clear_plan",
    "list_file_versions", "rollback_file", "list_files",
]

_base_tools: List[Any] = [
    read_file, list_files, edit_file, write_file, get_file_line_count,
    create_code_file, append_code_snippet,
    save_plan, load_plan, update_plan, clear_plan,
    list_file_versions, rollback_file,
    search_in_files, run_command, create_pdf, ask_user,
    web_search, web_fetch, web_search_and_read, get_documentation, code_interpreter,
    get_rag_tool(),
]

if _HAS_GIT_TOOLS:
    _base_tools.extend([git_log, git_diff, git_rollback_file, git_status])

if _HAS_C7_TOOLS:
    _base_tools.extend([resolve_library, get_library_docs])

try:
    from .tools.thinking_tool import think, show_diff, analyze_code
    _base_tools.extend([think, show_diff, analyze_code])
except ImportError:
    pass

try:
    from .tools.browser_tool import browser_get_text, browser_screenshot, browser_click_and_get, browser_evaluate
    _HAS_BROWSER_TOOLS = True
except ImportError:
    _HAS_BROWSER_TOOLS = False


_agent_mode_tools: List[Any] = []
if _HAS_BROWSER_TOOLS:
    _agent_mode_tools.extend([browser_get_text, browser_screenshot, browser_click_and_get, browser_evaluate])


def build_tools(agent_mode: bool = False) -> List[Any]:
    """Build full tool list (base + custom + optionally agent-mode browser tools)."""
    custom = load_custom_tools()
    all_tools = list(_base_tools) + list(custom)
    if agent_mode and _agent_mode_tools:
        all_tools.extend(_agent_mode_tools)
    return all_tools, custom


def get_agent_mode_tools() -> List[Any]:
    """Return browser/automation tools for Agent mode."""
    return list(_agent_mode_tools)


def build_tool_map(tools: List[Any]) -> Dict[str, BaseTool]:
    """Build name -> tool dispatch map."""
    tool_map: Dict[str, BaseTool] = {}
    for t in tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", None)
        if name:
            tool_map[str(name)] = t
    return tool_map


def bind_tools_safe(llm_obj: Any, model_name: str, tools: List[Any],
                    force_no_parallel: bool = False) -> Any:
    """Bind tools respecting provider capabilities."""
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
    """Reload custom tools and return updated tool list."""
    custom_new = reload_custom_tools()
    current_tools.clear()
    current_tools.extend(_base_tools + list(custom_new))
    return custom_new
