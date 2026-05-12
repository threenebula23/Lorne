# Сводная таблица инструментов

Источник истины по составу: `Agent/tool_registry.py` (`_base_tools`, `build_tools`, `_ASK_EXCLUDED_TOOL_NAMES`, `_CUSTOM_TOOL_NAMES`).

Легенда:

- **Base** — всегда в сессии при включённых custom tools (кроме фильтра Ask).
- **+Git** — `git_ops`, если импорт `git_tool` успешен.
- **+Agent** — добавляется в режимах с `agent_mode=True` при prefs: `headless_browser` (если `browser_tools_enabled`), `playwright_sync` (если `playwright_python_enabled`).

## Имя у модели → реализация

| Имя | Где реализовано |
|-----|-----------------|
| `read_file` | `Agent/tools/file_ops.py` |
| `read_file_lines` | `Agent/tools/file_ops.py` |
| `list_files` | `Agent/tools/file_ops.py` |
| `edit_file` | `Agent/tools/file_ops.py` |
| `write_file` | `Agent/tools/file_ops.py` |
| `replace_file_lines` | `Agent/tools/file_ops.py` |
| `insert_file_lines` | `Agent/tools/file_ops.py` |
| `get_file_line_count` | `Agent/tools/file_ops.py` |
| `code_file_tool` | `Agent/tools/compact_tools.py` → `code_gen` |
| `plan_tool` | `Agent/tools/compact_tools.py` → `planning_tool` |
| `search_in_files` | `Agent/tools/file_ops.py` |
| `find_in_file` | `Agent/tools/file_ops.py` |
| `run_command` | `Agent/tools/terminal_tool.py` |
| `run_package_script` | `Agent/tools/qa_tool.py` |
| `download_file` | `Agent/tools/download_tool.py` |
| `create_pdf` | `Agent/tools/pdf_tool.py` |
| `ask_user` | `Agent/tools/interactive.py` |
| `web_search` | `Agent/tools/web_tool.py` |
| `web_fetch` | `Agent/tools/web_tool.py` |
| `start_background_task` | `Agent/tools/parallel_helper_tool.py` |
| `get_background_result` | `Agent/tools/parallel_helper_tool.py` |
| `ocr_tool` | `Agent/tools/compact_tools.py` |
| `office_document_read` | `Agent/tools/office_document_tool.py` |
| `docx_write_tool` | `Agent/tools/compact_tools.py` |
| `docx_document_advanced_ops` | `Agent/tools/office_document_tool.py` |
| `docxedit_tool` | `Agent/tools/compact_tools.py` |
| `pdf_styled_document_create` | `Agent/tools/office_document_tool.py` |
| `reasoning_tool` | `Agent/tools/compact_tools.py` |
| `code_interpreter` | `Agent/tools/code_interpreter.py` |
| `rag_search` | `Agent/rag/__init__.py` (`get_rag_tool`) |
| `project_brain_tool` | `Agent/tools/compact_tools.py` |
| `git_ops` | `Agent/tools/compact_tools.py` → `git_tool` (опционально) |
| `library_context` | `Agent/tools/compact_tools.py` → `context7_tool` |
| `file_versions_tool` | `Agent/tools/compact_tools.py` |
| `headless_browser` | `Agent/tools/compact_tools.py` (+Agent, prefs) |
| `playwright_sync` | `Agent/tools/compact_tools.py` (+Agent, prefs) |

Пользовательские туловые модули добавляются через `custom_tools` (см. [tool/REFERENCE.md](tool/REFERENCE.md#custom-tools)).

Детали аргументов и примеров: [tool/REFERENCE.md](tool/REFERENCE.md). Мульти-тулы: [COMPACT_TOOLS.md](COMPACT_TOOLS.md).
