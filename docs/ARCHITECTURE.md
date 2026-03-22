# Архитектура TCA — карта модулей для разработчиков

Документ описывает **назначение пакетов и файлов**, **поток данных** и **точки расширения**. Предполагается знакомство с Python и по желанию с LangGraph / Textual.

---

## 1. Два режима запуска

| Режим | Переменная / флаг | Точка входа | UI |
|--------|-------------------|-------------|-----|
| **TUI (IDE)** | `TCA_MODE=tui` по умолчанию | `tca.py` → `Agent.agent.run_tui_mode()` | Textual: панели, редактор, чат |
| **Classic CLI** | `TCA_MODE=classic` или `--classic` | `tca.py` → `Agent.agent.run_coding_agent_loop()` | Rich в терминале, ввод строками |

Оба режима используют **один и тот же агент** (LangGraph, инструменты, LLM), но разные оболочки ввода/вывода.

---

## 2. Верхняя схема зависимостей

```
                    ┌─────────────────────────────────────┐
                    │           tca.py                   │
                    │  (cwd, env=KEY, TCA_MODE, --classic)│
                    └──────────────┬────────────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │                                         │
              ▼                                         ▼
    ┌──────────────────┐                    ┌──────────────────────┐
    │ Agent.agent      │                    │ Agent.agent          │
    │ run_tui_mode()   │                    │ run_coding_agent_loop│
    └────────┬─────────┘                    └──────────┬───────────┘
             │                                         │
             ▼                                         │
    ┌──────────────────┐                               │
    │ Interface/       │                               │
    │ tui_app.TCAApp   │                               │
    │ tui_bridge       │◄── callbacks из graph ────────┤ (общий graph)
    └────────┬─────────┘                               │
             │                                         │
             ▼                                         ▼
    ┌────────────────────────────────────────────────────────────┐
    │ Agent.graph_runner  ·  Agent.tool_registry  ·  Agent.llm_*  │
    └────────────────────────────────────────────────────────────┘
```

---

## 3. Каталог `Agent/` — ядро

| Файл | Роль |
|------|------|
| **`agent.py`** | Старт TUI или classic CLI, создание `TUIBridge`, вызов графа, сессии, интеграция с чатом. |
| **`graph_runner.py`** | Узлы LangGraph: `call_model`, `execute_tools`, маршрутизация `should_continue`. |
| **`tool_registry.py`** | Сборка списка инструментов: `_base_tools`, кастомные, опционально browser (agent mode). `build_tools()`, `bind_tools_safe()`. |
| **`llm_provider.py`** | OpenRouter-клиент, профили (`fast`/`balanced`/`quality`), список моделей, ретраи. |
| **`command_router.py`** | Slash-команды (`/model`, `/plan`, …) в classic-режиме. |
| **`planner.py`** | Построение плана задачи через LLM, запись в `.tca_plan.json`. |
| **`message_utils.py`** | Санитизация истории, компактирование, усечение результатов инструментов. |
| **`git_integration.py`** | Обёртка над GitPython: статус, diff, автокоммиты при записи файлов (если включено). |
| **`creator_mode.py`** | Creator Mode: разбиение задачи, пул воркеров, агрегация результатов. |
| **`creator_provider.py`** | Выбор local vs heavy модели для подзадач. |
| **`multiagent.py`** | Логические «под-агенты» (`/agent`): несколько потоков задач в одном проекте, не параллельное исполнение. |
| **`path_utils.py`** | Разрешение путей относительно корня проекта. |
| **`spinner.py`** | Индикация ожидания LLM. |
| **`system_promt.py`** | Системный промпт (опечатка в имени файла сохранена для совместимости). |

### Подпакеты

| Каталог | Назначение |
|---------|------------|
| **`Agent/tools/`** | Реализации `@tool` для LangChain: файлы, терминал, git, web, RAG-обёртки, PDF, кастомные инструменты и т.д. См. `docs/TOOLS.md`. |
| **`Agent/rag/`** | Индексация проекта, чанкинг, `get_rag_tool()` для `rag_search`. |
| **`Agent/checkpoint/`** | SQLite-сессии: сообщения, восстановление диалога (`.tca_checkpoints.sqlite` и др.). |
| **`Agent/versioning/`** | SQLite-снимки содержимого файлов до правок, откат. |
| **`Agent/file_loading/`** | Загрузка/подготовка файлов для RAG и контекста. |

---

## 4. Каталог `Agent/tools/` — по файлам

Ниже — **логическая группа**, не полный перечень параметров (см. docstring в коде).

| Файл | Содержимое |
|------|------------|
| `file_ops.py` | `read_file`, `list_files`, `edit_file`, `search_in_files`, `write_file`, `get_file_line_count` |
| `terminal_tool.py` | `run_command` |
| `code_gen.py` | `create_code_file`, `append_code_snippet` |
| `planning_tool.py` | `save_plan`, `load_plan`, `update_plan`, `clear_plan` |
| `versioning_tool.py` | `list_file_versions`, `rollback_file` |
| `git_tool.py` | `git_log`, `git_diff`, `git_rollback_file`, `git_status` |
| `web_tool.py` | `web_search`, `web_fetch`, `web_search_and_read` |
| `code_interpreter.py` | Запуск Python в subprocess |
| `context7_tool.py` | Документация библиотек (`get_documentation`, …) |
| `pdf_tool.py` | `create_pdf` |
| `interactive.py` | `ask_user` |
| `custom_tools.py` | Загрузка пользовательских инструментов из `~/.tca_custom_tools` |
| `thinking_tool.py` | `think`, `show_diff`, `analyze_code` |
| `browser_tool.py` | Playwright: `browser_*` (подмешиваются в **agent mode** через `build_tools(agent_mode=True)`) |
| `__init__.py` | Реэкспорт публичных имён для `tool_registry` |

Регистрация нового инструмента: файл → экспорт в `__init__.py` → запись в `_base_tools` в `tool_registry.py` → см. `docs/EXTENDING.md`.

---

## 5. Каталог `Interface/` — TUI (Textual)

| Файл | Роль |
|------|------|
| **`tui_app.py`** | `TCAApp`: layout (explorer, редактор, терминал, git, чат), `ResizeHandle`, CSS. |
| **`tui_bridge.py`** | Singleton-мост: агент в фоне вызывает `call_from_thread` для обновления панелей, подтверждений, стопа. |
| **`themes.py`** | Темы оформления, применение к приложению. |
| **`ui_prefs.py`** | Сохранение пользовательских настроек UI (пути к `.tca/` и т.п.). |
| **`visualization.py`** | Rich-вывод для **classic** режима: результаты инструментов, RAG. |
| **`graph_display.py`** | Отображение прогресса Creator Mode (classic). |
| **`splash.py`**, **`input_widget.py`**, **`path_loading.py`** | Вспомогательные виджеты/экраны. |
| **`tui_app.tcss`** | Стили Textual для IDE. |

### `Interface/panels/`

| Файл | Панель |
|------|--------|
| `file_explorer.py` | Дерево файлов, открытие, контекстное меню, запуск файлов. |
| `code_editor.py` | Вкладки, обычные файлы + **Jupyter `.ipynb`** (ячейки, run, autosave). |
| `ai_chat.py` | Чат с агентом, выбор модели/режима, стоп. |
| `terminal_panel.py` | Встроенный терминал (textual-terminal). |
| `version_control.py` | Ветки, staging, commit (Git). |

Сообщения Textual (`FileSaved`, `ChatSubmitted`, …) связывают панели с `agent.py` без жёсткой связи на уровне импортов циклов — часто через `post_message` и мост.

---

## 6. Каталог `Terminal/` — альтернативный CLI

| Файл | Роль |
|------|------|
| `cli.py` | Парсинг аргументов, запуск. |
| `runner.py` | Кросс-платформенное выполнение shell-команд. |
| `__main__.py` | Точка входа `python -m Terminal`. |

Часто пользователь запускает **`python tca.py`** или команду **`tca`** из `install.sh`, а не `-m Terminal` напрямую.

---

## 7. Данные на диске (типичные пути)

| Путь | Модуль | Содержимое |
|------|--------|------------|
| `Agent/.env` | `dotenv` | `OPENROUTER_API_KEY` |
| `~/.tca_config.json` | `llm_provider` | Выбранная модель |
| `.tca_checkpoints.sqlite` | `checkpoint` | История сообщений сессий |
| `.tca_versions.sqlite` | `versioning` | Снимки файлов |
| `.tca_plan.json` | `planning_tool` | Текущий план |
| `~/.tca_custom_tools/*.py` | `custom_tools` | Пользовательские инструменты |
| `.tca/` (в проекте) | UI prefs и др. | Настройки интерфейса |

---

## 8. Поток одного запроса в TUI

1. Пользователь вводит текст в **`AIChatPanel`** → сообщение → **`agent.py`** (`_tui_run` / аналог).
2. Строится граф с историей из checkpoint при необходимости.
3. **`graph_runner`** вызывает LLM → при `tool_calls` — **`execute_tools`** (чтение параллельно, запись последовательно — см. код).
4. Результаты стримятся в чат через **`TUIBridge`** (`on_tool`, `on_token`, …).
5. Состояние сохраняется в SQLite через **`checkpoint`**.

---

## 9. Связанная документация

| Документ | Тема |
|----------|------|
| [README.md](../README.md) | Установка, команды пользователя, обзор |
| [EXTENDING.md](./EXTENDING.md) | Новые инструменты, модели, Creator |
| [TOOLS.md](./TOOLS.md) | Справочник инструментов агента |

---

## 10. Чеклист для нового разработчика

1. Запустить `tca` в тестовой папке с ключом OpenRouter.
2. Прочитать **`Agent/graph_runner.py`** (узлы графа) и **`Agent/tool_registry.py`** (список tools).
3. Для изменения поведения агента — **`system_promt.py`**, **`message_utils.py`**.
4. Для UI — **`Interface/tui_app.py`**, **`tui_bridge.py`**, нужная панель в **`Interface/panels/`**.
5. Для нового инструмента — **`docs/EXTENDING.md`** + тест вручную через чат.
