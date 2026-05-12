# Project Brain и RAG

## Назначение

Каталог `project_brain/` в корне workspace: Markdown (и `rag_manifest.json`), индексируется как источник RAG с меткой brain. Часть файлов **пересобирается** сканером (`project_brain_tool` с `action=refresh|reindex|scan`), часть **пишет модель**.

## Сканер vs модель

- **Сканер / Relator** перезаписывает корневые обзорные файлы и деревья модулей — не редактировать моделью напрямую (см. исключения в коде).
- **Модель** пишет через `project_brain_tool`:
  - `action=write_architecture` — совместимость, файл `agent_architecture.md`;
  - `action=write_brain` + `brain_rel_path` — общий случай.

Разрешённые пути для `write_brain` (реализация `Agent/project_brain/agent_architecture.py` — `write_brain_markdown`):

- `agent/**/*.md` (подкаталог `agent/` не затирается refresh);
- в корне `project_brain/`: файлы `*_notes.md`, `*_supplement.md`;
- `agent_architecture.md`.

**Запрещено** перезаписывать моделью: `overview.md`, `architecture.md`, `glossary.md`, `tools.md`, `flows.md`, `rag_manifest.json`, а также префиксы `modules/`, `machine/`, `services/`, `agents/`. Дополняй смысл через `agent/overview_notes.md` и т.п.

## Инструмент `project_brain_tool`

Действия (см. `Agent/tools/compact_tools.py`):

| action | Назначение |
|--------|------------|
| `refresh` / `reindex` / `scan` | Пересборка brain с диска + индексация |
| `write_architecture` | Только `agent_architecture.md` + `content`, `write_mode` |
| `write_brain` | `brain_rel_path` + `content`, `write_mode` append\|replace |

Схема аргументов и coerce: `Agent/tool_schemas.py` (`ProjectBrainToolArgs`, блок `project_brain_tool` в `_coerce_common_arg_mistakes`).

## Промпт для модели

Правила вставки в системный промпт: `Agent/prompts/project_brain_rules.py`.

## RAG

Индексация: `Agent/rag/__init__.py` (`index_project_brain`). После записи brain из тулов вызывается переиндексация согласно реализации тула / графа (`run_brain_sync_if_enabled` и т.д.).
