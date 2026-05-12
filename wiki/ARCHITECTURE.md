# Архитектура TCA (Lorne)

Краткая карта для разработчиков. Детали режимов: [MODES/README.md](MODES/README.md). Brain: [PROJECT_BRAIN.md](PROJECT_BRAIN.md).

## Запуск

| Режим | Env | Вход | UI |
|--------|-----|------|-----|
| TUI | `LORNE_MODE` / `TCA_MODE` по умолчанию `tui` | `lorne.py` → `Agent.agent.run_tui_mode()` | Textual: `Interface/tui_app.py` |
| Classic CLI | `…=classic` или `--classic` | `lorne.py` → `run_coding_agent_loop()` | Rich |

`python -m Terminal` и `tca.py` делегируют в `lorne.main`. См. [tutorials/quickstart.md](tutorials/quickstart.md).

## Поток данных (TUI)

```
lorne.py → Agent.agent (TUI) → Interface.LorneApp + TUIBridge
         → LangGraph (Agent/graph_runner.py) → tool_registry.build_tools → tools
```

Откат хода: `Agent/checkpoint/` + `Agent/versioning/`; SQLite в `project_data_dir`: `checkpoints.sqlite`, `versions.sqlite`. Пути: `Agent/runtime_paths.py` (`.lorne` приоритетно, иначе `.tca`).

## Основные пакеты

| Пакет | Роль |
|-------|------|
| `Agent/graph_runner.py` | Узлы графа, `execute_tools`, read-only параллельно |
| `Agent/tool_registry.py` | `_base_tools`, `build_tools`, Ask/Agent флаги |
| `Agent/tool_schemas.py` | Pydantic аргументы, coerce |
| `Agent/tools/` | Реализации `@tool`, `compact_tools.py` — мульти-тулы |
| `Agent/rag/` | Индексация, `rag_search` |
| `Agent/project_brain/` | Скан, Markdown brain, `write_brain_markdown` |
| `Agent/deep_solver/` | Deep Solver (отдельный цикл, локальная модель) |
| `Agent/creator_*.py` | Creator Mode |
| `Interface/` | Textual UI, `tui_bridge.py`, `panels/` |
| `Terminal/` | CLI-обёртка над `lorne` |

## Панели TUI

| Модуль | Назначение |
|--------|------------|
| `Interface/panels/ai_chat/` | Чат, режим, ввод, откат |
| `Interface/panels/workspace_center.py` | Вкладки чат + редактор |
| `Interface/panels/file_explorer.py` | Дерево, настройки |
| `Interface/panels/active_agents_panel.py` | Creator-дерево |

Стили: `Interface/tui_app.tcss`, темы: `Interface/themes.py`, `Interface/cli_theme.py`.

## Данные на диске

| Путь | Содержимое |
|------|------------|
| `project_data_dir` / `ui_settings.json` | prefs UI |
| `project_data_dir` / `*.sqlite` | checkpoints, versions |
| `~/.lorne_config.json` | глобальные настройки (legacy: `~/.tca_config.json`) |
| `Agent/.env` | ключи API (dotenv) |

## Дальше

- [TOOLS.md](TOOLS.md), [COMPACT_TOOLS.md](COMPACT_TOOLS.md), [tool/REFERENCE.md](tool/REFERENCE.md)
- [Interface/OVERVIEW.md](Interface/OVERVIEW.md), [Interface/SETTINGS.md](Interface/SETTINGS.md)
- [developer/ADDING_TOOLS.md](developer/ADDING_TOOLS.md)
