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
                    │      tca.py  ·  python -m Terminal    │
                    │  (cwd, env=KEY, TCA_MODE, --classic) │
                    └──────────────┬───────────────────────┘
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
| **`agent.py`** | Старт TUI или classic CLI; `TUIBridge` только в TUI; граф, сессии, снимки перед ходом, **`handle_rollback`** (откат чата + workspace). |
| **`graph_runner.py`** | Узлы LangGraph: `call_model`, `execute_tools`, маршрутизация `should_continue`. Read-only тулы из фиксированного набора выполняются **параллельно** (пул потоков), остальные — по очереди. При ошибке `bind_tools` из-за `parallel_tool_calls` — повторная привязка с `force_no_parallel`. |
| **`tool_registry.py`** | Сборка списка: `_base_tools` (в т.ч. мульти-тулы из `compact_tools.py`), кастомные, `build_tools(agent_mode, playwright_python)`, `set_tool_session_prefs`, `bind_tools_safe()`. |
| **`llm_provider.py`** | OpenRouter-клиент, профили (`fast`/`balanced`/`quality`), список моделей, ретраи. |
| **`command_router.py`** | Slash-команды (`/model`, `/plan`, …) в classic-режиме. |
| **`planner.py`** | Построение плана задачи через LLM (`build_plan`); сохранение в файл делает **`planning_tool`** → `.tca/plan.json`. |
| **`message_utils.py`** | Санитизация истории, компактирование, усечение результатов инструментов. |
| **`git_integration.py`** | Обёртка над GitPython: статус, diff, автокоммиты при записи файлов (если включено). |
| **`creator_mode.py`** | Creator Mode: воркеры, оркестрация (`sequential` / `parallel` / `supervisor` / `hierarchical`), сводка супервайзера. |
| **`creator_summary.py`** | Один формат Markdown-итога Creator для TUI, classic и записи в `messages`. |
| **`creator_provider.py`** | Конфиг Creator (`orchestration`, local/heavy, `max_workers`). |
| **`creator_orchestration.py`** | Роли воркеров, handoff, `synthesize_supervisor_report`. |
| **`multiagent.py`** | Логические «под-агенты» (`/agent`): несколько потоков задач в одном проекте, не параллельное исполнение. |
| **`path_utils.py`** | Разрешение путей относительно корня проекта. |
| **`spinner.py`** | Индикация ожидания LLM. |
| **`system_promt.py`** | Системный промпт (опечатка в имени файла сохранена для совместимости). |

### Подпакеты

| Каталог | Назначение |
|---------|------------|
| **`Agent/tools/`** | Реализации `@tool` для LangChain: файлы, терминал, git, web, RAG-обёртки, PDF, кастомные инструменты и т.д. См. [TOOLS.md](TOOLS.md). |
| **`Agent/rag/`** | Индексация проекта, чанкинг, `get_rag_tool()` для `rag_search`. |
| **`Agent/checkpoint/`** | SQLite: `sessions`, `checkpoints`, снимки ходов `turn_snapshots` / `turn_workspace_snapshots` (откат TUI — см. `restore_turn_workspace`). Файл: `.tca/checkpoints.sqlite`. |
| **`Agent/versioning/`** | SQLite-снимки содержимого файлов до правок, откат; снимки path→version для отката хода и удаление «новых после метки» файлов. Файл: `.tca/versions.sqlite`. |
| **`Agent/file_loading/`** | Загрузка/подготовка файлов для RAG и контекста. |

---

## 4. Каталог `Agent/tools/` — по файлам

Ниже — **логическая группа**, не полный перечень параметров (см. docstring в коде).

| Файл | Содержимое |
|------|------------|
| `file_ops.py` | `read_file`, `list_files`, `edit_file`, `search_in_files`, `write_file`, `get_file_line_count` |
| `terminal_tool.py` | `run_command` |
| `code_gen.py` | `create_code_file`, `append_code_snippet` (у модели — **`code_file_tool`**) |
| `planning_tool.py` | `save_plan`, … (у модели — **`plan_tool`**) |
| `compact_tools.py` | Диспетчеры: `plan_tool`, `docx_write_tool`, `docxedit_tool`, `ocr_tool`, `code_file_tool`, `git_ops`, `library_context`, `reasoning_tool`, `headless_browser`, `playwright_sync`, `file_versions_tool` |
| `versioning_tool.py` | `list_file_versions`, `rollback_file` (у модели — **`file_versions_tool`**) |
| `git_tool.py` | Низкоуровневые git-тулы (у модели — **`git_ops`**) |
| `web_tool.py` | `web_search`, `web_fetch` (`web_search_and_read` в реестр **не** входит) |
| `code_interpreter.py` | Запуск Python в subprocess |
| `context7_tool.py` | `resolve_library`, `get_library_docs`, `get_documentation` (у модели — **`library_context`**, включая `action=search`) |
| `office_document_tool.py` | Чтение/запись docx, `docx_document_advanced_ops`, PDF ReportLab |
| `docxedit_tools.py` | Правки docx с сохранением формата (у модели — **`docxedit_tool`**) |
| `pdf_tool.py` | `create_pdf` |
| `interactive.py` | `ask_user` |
| `custom_tools.py` | Загрузка пользовательских инструментов из `~/.tca_custom_tools` |
| `thinking_tool.py` | `think`, `show_diff`, `analyze_code` (у модели — **`reasoning_tool`**) |
| `browser_tool.py` | Node-скрипты Playwright (у модели в Agent — **`headless_browser`**) |
| `playwright_sync_tool.py` | Python Playwright (у модели — **`playwright_sync`**, только при флаге в UI) |
| `__init__.py` | Реэкспорт публичных имён для импортов и скриптов |

Регистрация: см. [EXTENDING.md](EXTENDING.md) и [COMPACT_TOOLS.md](COMPACT_TOOLS.md) — новый низкоуровневый `@tool` или ветка в `compact_tools.py` + `_base_tools` в `tool_registry.py`.

---

## 5. Каталог `Interface/` — TUI (Textual)

| Файл | Роль |
|------|------|
| **`tui_app.py`** | `TCAApp`: слева дерево + панель агентов, по центру вкладки (чат + файлы), CSS в `tui_app.tcss`. |
| **`tui_bridge.py`** | Singleton-мост: `call_from_thread` / `call_later`; `on_chat_user_message(turn_index)`, `on_chat_reload_messages` после отката или смены сессии. |
| **`themes.py`** | Темы оформления, применение к приложению. |
| **`ui_prefs.py`** | Тема, `density`, подсветка, акцент; **`playwright_python_enabled`**, **`browser_tools_enabled`**; пользовательские модели и пресеты **Ollama** / OpenRouter → `.tca/ui_settings.json`. |
| **`visualization.py`** | Rich-вывод для **classic** режима: результаты инструментов, RAG. |
| **`graph_display.py`** | Отображение прогресса Creator Mode (classic). |
| **`session_picker_screen.py`** | Модальный экран выбора сессии при старте TUI (открыть / удалить / новый чат). |
| **`splash.py`**, **`input_widget.py`**, **`path_loading.py`** | Вспомогательные виджеты/экраны. |
| **`tui_app.tcss`** | Стили Textual для IDE. |

Подробный разбор архитектуры TUI, моста и панелей: [Interface/OVERVIEW.md](Interface/OVERVIEW.md).

### `Interface/panels/`

| Файл | Панель |
|------|--------|
| `file_explorer.py` | Дерево файлов, вкладки настроек (персонализация, агенты, OpenRouter, Ollama), контекст в чат. |
| `active_agents_panel.py` | Дерево Creator / режимов; выбор воркера или «Общий чат». |
| `workspace_center.py` | Вкладки: постоянный чат + вкладки редактора/просмотра. |
| `code_editor.py` | Редактор файлов и **Jupyter `.ipynb`** (ячейки, run, autosave). |
| `ai_chat.py` | Чат, модель, режимы **Normal / Creator / Agent / Research**, контекст, метрики; у пользовательских сообщений — кнопка отката хода (`RollbackRequested` → `agent.handle_rollback`). |
| `terminal_panel.py`, `version_control.py` | Модули на месте; в текущем layout IDE могут не монтироваться — см. `tui_app.py`. |

Сообщения Textual (`FileSaved`, `ChatSubmitted`, …) связывают панели с `agent.py` без жёсткой связи на уровне импортов циклов — часто через `post_message` и мост.

---

## 6. Каталог `Terminal/` — тот же вход, что у `tca.py`

| Файл | Роль |
|------|------|
| `cli.py` | Как `tca.py`: `env=`, каталог проекта, `TCA_MODE`, флаги `--classic` / `--tui`. |
| `runner.py` | Кросс-платформенное выполнение shell-команд. |
| `__main__.py` | Точка входа `python -m Terminal`. |

По умолчанию **`python -m Terminal`** запускает **TUI**; для режима только чата: `python -m Terminal --classic` или `TCA_MODE=classic`.

---

## 7. Данные на диске (типичные пути)

| Путь | Модуль | Содержимое |
|------|--------|------------|
| `Agent/.env` | `dotenv` | `OPENROUTER_API_KEY` |
| `~/.tca_config.json` | `llm_provider`, Creator | Модель по умолчанию, секция `creator`, прочие глобальные настройки |
| `.tca/checkpoints.sqlite` | `checkpoint` | `sessions`, `checkpoints`, снимки ходов для отката |
| `.tca/versions.sqlite` | `versioning` | Версии содержимого файлов |
| `.tca/ui_settings.json` | `ui_prefs` | Тема, плотность, подсветка; браузерные тулы; свои модели и Ollama |
| `.tca/plan.json` | `planning_tool` | Текущий план |
| `~/.tca_custom_tools/*.py` | `custom_tools` | Пользовательские инструменты |

---

## 8. Поток одного запроса в TUI

1. Пользователь вводит текст в **`AIChatPanel`** → сообщение → **`agent.py`** (`_tui_run` / аналог). Перед добавлением `HumanMessage` сохраняются **`save_pre_turn_snapshot`** и **`save_pre_turn_workspace_snapshot`** (индекс хода = число предыдущих пользовательских сообщений).
2. Строится граф с историей из checkpoint при необходимости.
3. **`graph_runner`** вызывает LLM → при `tool_calls` — **`execute_tools`** (набор read-only-only → параллельно, иначе по очереди).
4. Результаты стримятся в чат через **`TUIBridge`** (`on_tool`, `on_token`, …).
5. Состояние сохраняется в SQLite через **`checkpoint`**. Откат хода: `load_pre_turn_snapshot` + **`restore_turn_workspace`**, затем удаление более новых снимков и `save_state`.

---

## 9. Связанная документация

| Документ | Тема |
|----------|------|
| [README.md](../README.md) | Установка, команды пользователя, обзор |
| [EXTENDING.md](EXTENDING.md) | Новые инструменты, модели, Creator |
| [TOOLS.md](TOOLS.md) | Справочник инструментов агента |
| [COMPACT_TOOLS.md](COMPACT_TOOLS.md) | Мульти-тулы и режим Agent / Playwright |

---

## 10. Чеклист для нового разработчика

1. Запустить `tca` в тестовой папке с ключом OpenRouter.
2. Прочитать **`Agent/graph_runner.py`** (узлы графа) и **`Agent/tool_registry.py`** (список tools).
3. Для изменения поведения агента — **`system_promt.py`**, **`message_utils.py`**.
4. Для UI — **`Interface/tui_app.py`**, **`tui_bridge.py`**, нужная панель в **`Interface/panels/`**.
5. Для нового инструмента — **[EXTENDING.md](EXTENDING.md)** + тест вручную через чат.
