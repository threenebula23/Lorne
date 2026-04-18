# Компактные инструменты (мульти-тулы)

Реализация: **`Agent/tools/compact_tools.py`**. Ниже — имена тулов **для модели** и соответствие «логике» старых отдельных тулов (которые по-прежнему есть в коде как `@tool` для вызова изнутри диспетчеров и для CLI).

---

## Сводка

| Тул у модели | Назначение |
|--------------|------------|
| **`plan_tool`** | План: `save` \| `load` \| `update` \| `clear` (раньше `save_plan`, `load_plan`, …) |
| **`docx_write_tool`** | `.docx`: `create` \| `append` \| `patch` + `data_json` |
| **`docxedit_tool`** | docxedit: `replace` \| `replace_limited` \| `find_line` \| `table_cell` \| `table_font` |
| **`ocr_tool`** | OCR: `soft` \| `medium` \| `strong` + `path` |
| **`code_file_tool`** | Код: `create` \| `append` |
| **`git_ops`** | Git: `status` \| `log` \| `diff` \| `rollback_file` |
| **`library_context`** | Доки: `resolve` \| `docs` \| **`search`** (бывший `get_documentation`; общий веб — `web_fetch`) |
| **`reasoning_tool`** | `think` \| `diff` \| `analyze` |
| **`file_versions_tool`** | Версии файла: `list` \| `rollback` |
| **`headless_browser`** | Node Playwright (только **режим Agent**): `get_text` \| `screenshot` \| `click_and_get` \| `evaluate` |
| **`playwright_sync`** | Python Playwright (только Agent **и** галочка в Settings) |

Остаются **отдельными** (не схлопнуты в один диспетчер): `read_file`, `edit_file`, `write_file`, `replace_file_lines`, `insert_file_lines`, `search_in_files`, `run_command`, `web_search`, `web_fetch`, `office_document_read`, `docx_document_advanced_ops`, `pdf_styled_document_create`, `code_interpreter`, `rag_search`, `ask_user`, `create_pdf`, `think`/`show_diff`/`analyze_code` **не** в списке у модели — только **`reasoning_tool`**.

---

## Что убрано из списка у модели (но не из кода)

- **`web_search_and_read`** — нет в реестре; цепочка `web_search` → `web_fetch`.
- **`get_documentation`** — сценарий перенесён в **`library_context(action="search", query=..., library_name=...)`**.

---

## Режим Agent и Playwright (Python)

- В **TUI** при режиме **Agent** список тулов пересобирается (`_sync_tui_tool_bundle` в `Agent/agent.py`): добавляются **`headless_browser`** и при настройке — **`playwright_sync`**.
- Галочка **«Python Playwright (Chromium)»** в **Files → Settings** сохраняется в **`.tca/ui_settings.json`** (`playwright_python_enabled`). После смены — сообщение в следующем чате в Agent или переключение режима.
- Подробности поведения — в **`Agent/system_promt.py`**.

---

## Расширение

Новый низкоуровневый `@tool` по-прежнему добавляют в `Agent/tools/`, экспорт в `__init__.py`, затем в **`_base_tools`** в `tool_registry.py`. Чтобы попасть в **мульти-тул**, добавьте ветку `action` в `compact_tools.py` и опишите в `system_promt.py`.

См. также: [TOOLS.md](TOOLS.md), [ARCHITECTURE.md](ARCHITECTURE.md), [EXTENDING.md](EXTENDING.md).
