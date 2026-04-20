# Справочник инструментов TCA

Агент видит **ограниченный набор имён тулов** (меньше схем = дешевле контекст на `bind_tools`). Часть сценариев объединена в **мульти-тулы** с полем `action` — см. **[COMPACT_TOOLS.md](COMPACT_TOOLS.md)**.

Детальный разбор **исходного кода** по файлам — в папке [tool/](tool/) (имена функций там могут быть «низкоуровневыми», например `save_plan` внутри `plan_tool`).

---

## Сводная таблица (как вызывает модель)

| Категория | Инструмент | Описание | Код / подробнее |
|-----------|------------|----------|-----------------|
| **Файлы** | `read_file`, `edit_file`, `write_file`, `list_files`, `search_in_files` | Чтение, правки, список, поиск | [file_ops.md](tool/file_ops.md) |
| | `replace_file_lines`, `insert_file_lines`, `get_file_line_count` | Правки по строкам, размер | [file_ops.md](tool/file_ops.md) |
| | **`code_file_tool`** | `create` \| `append` кода | [code_gen.md](tool/code_gen.md) |
| **План** | **`plan_tool`** | `save` \| `load` \| `update` \| `clear` | [planning_tool.md](tool/planning_tool.md) |
| **Рассуждения** | **`reasoning_tool`** | `think` \| `diff` \| `analyze` | [thinking_tool.md](tool/thinking_tool.md) |
| **Система** | `run_command` | Shell с подтверждением; опц. дедуп — `TCA_RUN_COMMAND_DEDUPE_S` | [terminal_tool.md](tool/terminal_tool.md) |
| | **`start_background_task`**, **`get_background_result`** | Фоновый микро-цикл LLM+тулов, пока основной граф занят | [BACKGROUND_AND_DEEP.md](BACKGROUND_AND_DEEP.md) |
| | **`download_file`** | Скачать URL в файл в воркспейсе (лимит размера) | [download_tool.py](../Agent/tools/download_tool.py) |
| | `code_interpreter` | Python в subprocess | [code_interpreter.md](tool/code_interpreter.md) |
| **Git** | **`git_ops`** | `status` \| `log` \| `diff` \| `rollback_file` | [git_tool.md](tool/git_tool.md) |
| **Версии файла** | **`file_versions_tool`** | `list` \| `rollback` | [versioning_tool.md](tool/versioning_tool.md) |
| **Веб** | `web_search`, `web_fetch` | Поиск и загрузка страницы (без `web_search_and_read` в реестре) | [web_tool.md](tool/web_tool.md) |
| **Доки библиотек** | **`library_context`** | `resolve` \| `docs` \| **`search`** (бывший get_documentation) | [context7_tool.md](tool/context7_tool.md) |
| **OCR** | **`ocr_tool`** | `soft` \| `medium` \| `strong` | (см. `Agent/tools/ocr_tool.py`) |
| **Office** | `office_document_read`, **`docx_write_tool`**, `docx_document_advanced_ops`, **`docxedit_tool`**, `pdf_styled_document_create` | Word/PDF | [pdf_tool.md](tool/pdf_tool.md), `office_document_tool.py` |
| **RAG / PDF / чат** | `rag_search`, `create_pdf`, `ask_user` | Поиск по проекту, PDF, вопрос пользователю | [pdf_tool.md](tool/pdf_tool.md), [interactive.md](tool/interactive.md) |
| **Кастом** | через `/custom` | Пользовательские тулы | [custom_tools.md](tool/custom_tools.md) |
| **Agent (TUI)** | **`headless_browser`**, **`playwright_sync`** | Браузер Node / Python; второй — только при галочке Settings | [browser_tool.md](tool/browser_tool.md), [COMPACT_TOOLS.md](COMPACT_TOOLS.md) |

---

## Базовые сценарии

### Файлы
Агент использует `file_ops.py`. Большие файлы — `read_file` с `offset`/`limit`.

### План
`plan_tool(action="save", title="...", steps_json='["шаг1","шаг2"]')` — затем `update` / `load` / `clear`.

### Веб и документация
1. Узкий поиск — `web_search`.  
2. Конкретный URL — `web_fetch`.  
3. Документация пакета — `library_context`: при неизвестном id сначала `resolve`, затем `docs`; размытый запрос — `search` + при необходимости `web_fetch`.

### Фоновый помощник и долгий терминал
Если сначала нужен **короткий** тест/проверка, а затем **долгий** `run_command` (сервер, сборка), используй `start_background_task` → `run_command` → `get_background_result` — см. [BACKGROUND_AND_DEEP.md](BACKGROUND_AND_DEEP.md). Для **Deep Solver** (локальная модель) — `spawn_subagent` / `get_subagent_result` в том же документе.

### Версии и Git
Снимки SQLite перед правками; откат одного файла через модель — **`file_versions_tool`**, в classic также slash-команды `/versions` и `/rollback`. В **TUI** дополнительно откат **целого хода** диалога (кнопка у сообщения пользователя) восстанавливает файлы по снимкам сессии — см. [ARCHITECTURE.md](ARCHITECTURE.md) §8. Git — **`git_ops`**.

### Creator Mode
Параллельные воркеры используют **тот же** список тулов, что и основной чат (в т.ч. компактные имена). Настройки: `wiki/EXTENDING.md` (`orchestration`, local/heavy).

---

## Связанные документы

- [COMPACT_TOOLS.md](COMPACT_TOOLS.md) — полная таблица `action` и соответствие legacy-функциям  
- [ARCHITECTURE.md](ARCHITECTURE.md) — `tool_registry`, `graph_runner`  
- [BACKGROUND_AND_DEEP.md](BACKGROUND_AND_DEEP.md) — фоновый помощник и Deep Solver  
- [EXTENDING.md](EXTENDING.md) — добавление своих тулов и Creator  
