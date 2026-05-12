# Режим: ask

## Реализация

- Ключ `_MODE_ADDONS["ask"]` в `Agent/prompts/__init__.py`.
- `build_tools(ask_mode=True)` фильтрует список: имена из `_ASK_EXCLUDED_TOOL_NAMES` в `Agent/tool_registry.py` удаляются из сессии.

## Схема потока

```mermaid
flowchart LR
  user[User] --> chat[Chat]
  chat --> graph[Agent_graph]
  graph --> llm[LLM]
  llm --> tools[Read_only_tools]
```

## Инструменты

**Недоступны** (имена): `edit_file`, `write_file`, `replace_file_lines`, `insert_file_lines`, `code_file_tool`, `docx_write_tool`, `docxedit_tool`, `docx_document_advanced_ops`, `pdf_styled_document_create`, `git_ops`, `download_file`, `run_command`, `start_background_task`, `get_background_result`, `run_package_script`, `create_pdf`, `file_versions_tool`, `code_interpreter`, `project_brain_tool`.

**Доступны** (типично): чтение файлов, поиск по репо, `web_search` / `web_fetch`, `library_context`, `rag_search` (если custom tools включены), `ask_user`, `reasoning_tool`, `ocr_tool`, `office_document_read`, и др. из оставшегося списка после фильтра.
