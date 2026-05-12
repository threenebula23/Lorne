# Компактные инструменты (multi-tools)

Реализация: **`Agent/tools/compact_tools.py`**. У модели одно имя тула и поле `action` (и общие поля), внутри вызываются существующие `@tool` или функции.

## Список мульти-тулов

| Имя у модели | Назначение |
|---------------|------------|
| `plan_tool` | План: `save` \| `load` \| `update` \| `clear` |
| `docx_write_tool` | DOCX: `create` \| `append` \| `patch` + `data_json` |
| `docxedit_tool` | Точечные правки docx: `replace` \| `replace_limited` \| `find_line` \| `table_cell` \| `table_font` |
| `ocr_tool` | `soft` \| `medium` \| `strong` + `path` |
| `code_file_tool` | Код: `create` \| `append` |
| `git_ops` | Git: `status` \| `log` \| `diff` \| `rollback_file` |
| `library_context` | Документация библиотек: `resolve` \| `docs` \| `search` и др. |
| `reasoning_tool` | `think` \| `diff` \| `analyze` (и алиасы) |
| `headless_browser` | Node Playwright (режим Agent + настройка браузера) |
| `playwright_sync` | Python Playwright (Agent + `playwright_python_enabled`) |
| `file_versions_tool` | Версии файла: `list` \| `rollback` |
| `project_brain_tool` | Brain: `refresh` \| `reindex` \| `scan` \| `write_architecture` \| `write_brain` |

Атомарные тулы (`read_file`, `edit_file`, …) остаются отдельными импортами из `Agent/tools/*` — см. [TOOLS.md](TOOLS.md).

## Добавление ветки в compact tool

1. Реализовать делегирование в `compact_tools.py`.
2. Добавить/обновить Pydantic-модель в `Agent/tool_schemas.py` и `TOOL_ARG_MODELS`.
3. При необходимости — `_coerce_common_arg_mistakes`.
4. Обновить эту таблицу и [tool/REFERENCE.md](tool/REFERENCE.md).

Полный чеклист: [developer/ADDING_TOOLS.md](developer/ADDING_TOOLS.md).
