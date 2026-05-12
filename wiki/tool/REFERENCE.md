# Справочник по инструментам (секции)

Единый файл вместо набора устаревших `wiki/tool/*.md`. Детали смотрите в docstring и `Agent/tool_schemas.py`.

---

## Файловые операции

- **`read_file`**, **`read_file_lines`**, **`list_files`**, **`edit_file`**, **`write_file`**, **`replace_file_lines`**, **`insert_file_lines`**, **`search_in_files`**, **`find_in_file`**, **`get_file_line_count`** — `Agent/tools/file_ops.py`. Пути относительно корня проекта.

---

## Терминал и пакеты

- **`run_command`** — `terminal_tool.py`; опциональный дедуп env `LORNE_RUN_COMMAND_DEDUPE_S` / `TCA_RUN_COMMAND_DEDUPE_S`.
- **`run_package_script`** — `qa_tool.py`.

---

## Веб

- **`web_search`**, **`web_fetch`** — `web_tool.py`.

---

## Параллельный фон

- **`start_background_task`**, **`get_background_result`** — `parallel_helper_tool.py`.

---

## Office / PDF

- **`office_document_read`**, **`docx_document_advanced_ops`**, **`pdf_styled_document_create`** — `office_document_tool.py`.
- Компактные обёртки: **`docx_write_tool`**, **`docxedit_tool`** — см. [COMPACT_TOOLS.md](../COMPACT_TOOLS.md).

---

## OCR

- **`ocr_tool`** — диспетчер в `compact_tools.py` → `ocr_tool.py` (`soft` / `medium` / `strong`).

---

## Код и интерпретатор

- **`code_file_tool`** — `compact_tools.py` → `code_gen.py`.
- **`code_interpreter`** — `code_interpreter.py`.

---

## План

- **`plan_tool`** — `compact_tools.py` → `planning_tool.py`. Аргументы: `PlanToolArgs` в `tool_schemas.py`. Coerce принимает `steps` / `items` / `tasks` как массив и сериализует в `steps_json`.

---

## RAG

- **`rag_search`** — `Agent/rag/__init__.py`. Отключается вместе с другими «custom» тулами при выключенном переключателе в UI.

---

## Project Brain

- **`project_brain_tool`** — см. [PROJECT_BRAIN.md](../PROJECT_BRAIN.md). Действия: `refresh`, `reindex`, `scan`, `write_architecture`, `write_brain` (+ `brain_rel_path`).

---

## Git и версии файла

- **`git_ops`** — `compact_tools.py` (если доступен низкоуровневый git-tool).
- **`file_versions_tool`** — `compact_tools.py` → `versioning_tool.py`.

---

## Документация библиотек (Context7)

- **`library_context`** — `compact_tools.py` → `context7_tool.py`. Поля: `LibraryContextArgs`.

---

## Рассуждение

- **`reasoning_tool`** — `compact_tools.py`. Действия: `think`, `diff`, `analyze`, … См. `ReasoningToolArgs`.

---

## Браузер

- **`headless_browser`** — Node Playwright.
- **`playwright_sync`** — Python Playwright.

Подключаются только при `agent_mode` и соответствующих prefs.

---

## Прочее

- **`download_file`**, **`create_pdf`**, **`ask_user`** — см. `download_tool.py`, `pdf_tool.py`, `interactive.py`.

---

## Custom tools

Загрузка из `~/.lorne_custom_tools` (legacy: `~/.tca_custom_tools`): `custom_tools.py` — `load_custom_tools`, `add_custom_tool`, … Отображаются в списке тулов, если включено в настройках.

---

## Валидация аргументов

Перед вызовом: `Agent/tool_schemas.validate_tool_arguments` и `_coerce_common_arg_mistakes` для части тулов (в т.ч. `plan_tool`, `project_brain_tool`).
