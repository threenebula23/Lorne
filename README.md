# Lorne v0.98 — терминальный ассистент для кода


![](./wiki/image.png)



**Документация:** [wiki/README.md](wiki/README.md) · [wiki/tutorials/quickstart.md](wiki/tutorials/quickstart.md) · [wiki/MODES/README.md](wiki/MODES/README.md) · [wiki/PROJECT_BRAIN.md](wiki/PROJECT_BRAIN.md) · [wiki/ARCHITECTURE.md](wiki/ARCHITECTURE.md) · [wiki/TOOLS.md](wiki/TOOLS.md) · [wiki/COMPACT_TOOLS.md](wiki/COMPACT_TOOLS.md) · [wiki/BACKGROUND_AND_DEEP.md](wiki/BACKGROUND_AND_DEEP.md) · [wiki/EXTENDING.md](wiki/EXTENDING.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [docs/README.md](docs/README.md)

## Возможности

- **Работа с файлами** — чтение (с пагинацией), создание, редактирование, поиск по содержимому
- **Терминал** — выполнение shell-команд с подтверждением пользователя
- **Планирование** — автоматическое построение плана для сложных задач с отслеживанием прогресса
- **Версионирование** — SQLite-снимки файлов + Git-интеграция (автокоммиты, откат, история)
- **RAG-поиск** — семантический чанкинг, word-level scoring, mtime-кэш, инкрементальная переиндексация
- **Сессии** — сохранение и восстановление диалогов между запусками (SQLite), именованные чаты, модальный выбор сессии при старте TUI
- **Откат хода (TUI)** — у каждого пользовательского сообщения кнопка отката: восстанавливается история диалога до этого хода и рабочая копия файлов по снимкам версий (каталог данных проекта: ``.lorne`` или существующий legacy ``.tca`` — см. ``Agent/runtime_paths.py``)
- **Красивый UI** — Rich-панели, подсветка синтаксиса, прогресс-бары, Markdown, подсказки команд
- **Много моделей** — 27+ моделей через OpenRouter (бесплатные, дешёвые, платные, про)
- **Creator Mode** — параллельное выполнение подзадач несколькими агентами (local + heavy модели)
- **Параллельные инструменты** — read-only инструменты выполняются параллельно для ускорения
- **Фоновый помощник** — `start_background_task` / `get_background_result`: отдельный короткий LLM+инструменты в потоке, пока основной граф занят долгим `run_command` (сервер, сборка); после задачи помощник завершается
- **Deep Solver** — длительный автономный режим на **локальной** модели (Ollama и т.п.): чекпоинты, `spawn_subagent` / `get_subagent_result` для фоновой микрозадачи без блокировки долгого терминала
- **Устойчивость к «петлям»** — подсказки при повторяющихся вызовах одних и тех же тулов; в промпте — смена стратегии (`web_search`, план) вместо того же шага
- **Локальные модели** — доразбор `tool_calls`, восстановление JSON, извлечение «мыслей» / `<thought>`, подсказки при шумных ответах
- **Генерация PDF** — создание документов через ReportLab

---

## Быстрый старт

### Требования

- Python 3.10+
- API-ключ [OpenRouter](https://openrouter.ai/) (есть бесплатные модели)

### Установка

**macOS / Linux:**

```bash
git clone https://github.com/threenebula23/TCA.git
cd TCA
chmod +x install.sh
./install.sh
```

**Windows:**

```cmd
git clone https://github.com/threenebula23/TCA.git
cd TCA
install.bat
```

Скрипт установки:
1. Создаёт виртуальное окружение `.venv`
2. Устанавливает зависимости из `requirements.txt`
3. Создаёт команды **`lorne`** и **`tca`** (алиас к тому же запуску) в PATH

### Первый запуск

```bash
# С ключом через аргумент
lorne env=sk-or-v1-ваш_ключ

# Или сохранить ключ в файл
echo 'OPENROUTER_API_KEY=sk-or-v1-ваш_ключ' > Agent/.env
lorne
```

---

## Использование

### Запуск

```bash
lorne                          # работает в текущей директории
lorne /path/to/project         # работает в указанном проекте
lorne env=sk-or-v1-xxx         # передать API-ключ через аргумент
lorne /path/to/project env=KEY # оба варианта (любой порядок)
```


По умолчанию запускается **TUI-IDE** (Textual). Классический режим — только чат в терминале (Rich):

```bash
TCA_MODE=classic lorne
# или
lorne --classic
python -m Terminal --classic
```

Явно включить TUI: `lorne --tui` или `TCA_MODE=tui` (значение по умолчанию).

Альтернативный способ запуска (без установки) — тот же разбор `env=` и каталога через `python tca.py`:

```bash
python tca.py
python -m Terminal              # TUI; для classic: python -m Terminal --classic
```

### Интерфейс

После запуска Lorne покажет приветственный экран с текущей моделью, профилем и проектом (в TUI затем — выбор сессии). В панели чата доступны режимы **Normal**, **Creator**, **Agent** (расширенный набор инструментов, в т.ч. браузер по настройкам) и **Research** (префикс к запросу для упора на веб-источники). Далее — интерактивный цикл ввода задач.

**Пример сессии:**

```
❯ создай файл calculator.py с функциями add, sub, mul, div и тестами к нему
  📋 Составляю план: создай файл calculator.py с функциями add, sub, mul, div...
  ✓ План создан: 4 шагов

  ═══ Агент работает ═══
  ⚡ create_code_file { filepath: "calculator.py", language: "python", ... }
  ✓ Создан  calculator.py  25 строк (+25)
  ⚡ create_code_file { filepath: "test_calculator.py", language: "python", ... }
  ✓ Создан  test_calculator.py  32 строк (+32)
  ⚡ run_command { command: "python -m pytest test_calculator.py -v" }
  ✓ Код выхода: 0
  ...
```

### Команды

| Команда | Описание |
|---|---|
| `Enter` (пустой ввод) | Продолжить — агент выполнит следующий шаг |
| `!<команда>` | Выполнить команду в терминале напрямую (например `!ls -la`, `!git status`) |
| `/model` | Выбрать модель из списка (выбор сохраняется) |
| `/model <id>` | Установить произвольную модель по ID |
| `/profile [имя]` | Сменить профиль: `fast`, `balanced`, `quality` |
| `/balance` | Показать баланс OpenRouter |
| `/plan` | Показать текущий план задачи (без LLM) |
| `/status` | Информация о модели, контексте, RAG, сообщениях |
| `/ls [путь]` | Список файлов в директории |
| `/tree [путь]` | Дерево проекта |
| `/rag <запрос>` | Прямой поиск по проекту (RAG) без LLM |
| `/versions <файл>` | История версий файла (SQLite) |
| `/rollback <файл> [id]` | Откатить **один файл** к версии из SQLite (classic и общий сценарий; в TUI дополнительно есть **откат целого хода** — кнопка у сообщения пользователя) |
| `/git status` | Статус Git-репозитория |
| `/git log [файл]` | История Git-коммитов |
| `/git diff [хеш]` | Git diff текущих изменений или коммита |
| `/git rollback <хеш>` | Откатить Git-коммит (revert) |
| `/compact` | Сжать историю разговора (освободить контекст) |
| `/creator` | Включить/выключить Creator Mode (параллельные агенты) |
| `/creator <задача>` | Запустить задачу в Creator Mode |
| `/creator set orchestration …` | `parallel` \| `sequential` \| `supervisor` \| `hierarchical` (см. [EXTENDING.md](wiki/EXTENDING.md)) |
| `/custom` | Управление кастомными инструментами |
| `/agent list` | Список логических под-агентов |
| `/help` | Справка по командам |
| `/exit` | Выйти |

### Сессии

В **TUI** при старте открывается модальное окно со списком чатов: для каждой сессии видны заголовок, время обновления и примерное число сообщений. Доступны **Открыть**, **Удалить**, **Новый чат** и **Выход из TCA**.

В **classic**-режиме по-прежнему текстовый выбор: **Enter** — новая сессия, **номер** — продолжить, **d номер** — удалить.

Сессии и история сообщений хранятся в **`.tca/checkpoints.sqlite`**. Дополнительно для отката ходов ведутся снимки диалога и снимок «версий файлов проекта» на границе каждого пользовательского сообщения (таблицы `turn_snapshots`, `turn_workspace_snapshots`).

---

## Конфигурация

### API-ключ

Три способа указать ключ OpenRouter (в порядке приоритета):

1. **Аргумент запуска:** `lorne env=sk-or-v1-xxx` (или `tca env=…`)
2. **Файл `.env`:** создать `Agent/.env` или `.env` в корне TCA с содержимым `OPENROUTER_API_KEY=sk-or-v1-xxx`
3. **Переменная окружения:** `export OPENROUTER_API_KEY=sk-or-v1-xxx`

### Профили

| Профиль | Temperature | Max tokens | Назначение |
|---|---|---|---|
| `fast` | 0.1 | 4096 | Быстрые простые задачи |
| `balanced` | 0.2 | 8192 | Баланс скорости и качества (по умолчанию) |
| `quality` | 0.1 | 16384 | Максимальное качество |

### Переменные окружения

| Переменная | Описание | По умолчанию |
|---|---|---|
| `OPENROUTER_API_KEY` | API-ключ OpenRouter | — (обязательно) |
| `TCA_MODE` | `tui` (IDE) или `classic` (чат в терминале) | `tui` |
| `TCA_PROFILE` | Профиль по умолчанию | `balanced` |
| `TCA_MODEL` | Модель по умолчанию | `arcee-ai/trinity-large-preview:free` |
| `TCA_BASE_URL` | Base URL для API | `https://openrouter.ai/api/v1` |
| `TCA_MODEL_FAST` | Модель для профиля fast | значение `TCA_MODEL` |
| `TCA_MODEL_BALANCED` | Модель для профиля balanced | значение `TCA_MODEL` |
| `TCA_MODEL_QUALITY` | Модель для профиля quality | значение `TCA_MODEL` |
| `TCA_TEMP_FAST` | Temperature для fast | `0.1` |
| `TCA_TEMP_BALANCED` | Temperature для balanced | `0.2` |
| `TCA_TEMP_QUALITY` | Temperature для quality | `0.1` |
| `TCA_MAX_TOKENS` | Max tokens (глобально) | `8192` |
| `TCA_MAX_TOKENS_FAST` | Max tokens для fast | `4096` |
| `TCA_MAX_TOKENS_BALANCED` | Max tokens для balanced | `8192` |
| `TCA_MAX_TOKENS_QUALITY` | Max tokens для quality | `16384` |
| `TCA_RAG_PATTERNS` | Паттерны для RAG-индексации | `*.py,*.md,*.ts,*.tsx,*.json` |
| `TCA_RAG_MAX_FILES` | Макс. число файлов для RAG | `500` |
| `TCA_RUN_COMMAND_DEDUPE_S` | Окно анти-спама для **повторной той же** `run_command` (сек.); **0** = отключено | `0` |
| `LOCAL_API_KEY` | API-ключ для локального сервера (Creator Mode) | — |

### Доступные модели

Команда `/model` показывает полный список. Краткая сводка:

**Бесплатные:**
Trinity Large, Step 3.5 Flash, Qwen3 235B Thinking

**Платные:**
Qwen3 235B Thinking, Qwen3 Coder 30B, Qwen3.5 Flash, GPT OSS 120B, GPT-5 Nano, Gemini 2.5 Flash Lite

**Доступные (cheap):**
Qwen3 Coder Next, Qwen3.5 35B, Qwen3 Coder, Qwen3.5 Plus, Qwen3.5 397B, GPT-4o Mini, GPT-5 Mini, Gemini 2.5 Flash, Gemini 3 Flash, Grok 4.1 Fast, Grok Code Fast, DeepSeek V3.2

**Про (pro):**
GPT-5.1 Codex, GPT-5.3 Codex, Gemini 3.1 Pro, Claude Haiku 4.5, Claude Sonnet 4.6, Claude Opus 4.6

Выбор модели сохраняется в `~/.tca_config.json` между запусками.

---

## Архитектура

Подробная карта модулей, потоков данных и путей к SQLite — в **[wiki/ARCHITECTURE.md](wiki/ARCHITECTURE.md)**.

### Структура проекта (кратко)

```
TCA/
├── tca.py                      # Точка входа Python; после install — команды lorne и tca (алиас)
├── requirements.txt
├── wiki/                       # ARCHITECTURE.md, EXTENDING.md, TOOLS.md, BACKGROUND_AND_DEEP.md
│
├── Agent/                      # Ядро: LLM, LangGraph, инструменты, RAG, сессии
│   ├── agent/                  # run_tui_mode / run_coding_agent_loop; снимки, откат TUI
│   ├── graph_runner.py         # LangGraph: call_model, execute_tools, анти-петля
│   ├── tool_registry.py        # build_tools(agent_mode, playwright_python), compact + custom
│   ├── message_utils/          # Санитизация, компактирование, восстановление tool JSON, петли тулов
│   ├── deep_solver/            # Пакет Deep Solver; legacy_loop.py — долгий цикл, чекпоинты
│   ├── background_agent_runner.py  # Фоновый LLM+тул-цикл для start_background_task
│   ├── command_router/         # Slash-команды в classic-режиме
│   ├── llm_provider.py         # OpenRouter, профили, модели
│   ├── planner.py              # Планы задач
│   ├── git_integration.py      # GitPython
│   ├── creator_mode.py         # Creator: воркеры, оркестрация, супервайзер
│   ├── creator_orchestration.py  # Роли, handoff, сводка супервайзера
│   ├── creator_summary.py      # Единый текст итога Creator (TUI + classic + сессия)
│   ├── creator_provider.py     # Конфиг Creator (orchestration, local/heavy)
│   ├── system_promt.py         # Системный промпт (тул-стратегия, веб, фоновый помощник)
│   ├── tools/                  # @tool + compact_tools.py; parallel_helper_tool, download_tool, …
│   ├── rag/                    # Индексация и rag_search
│   ├── checkpoint/             # Сессии (SQLite)
│   ├── versioning/             # Снимки файлов (SQLite)
│   └── file_loading/           # Загрузка файлов для RAG
│
├── Interface/                  # TUI (Textual) + Rich для classic
│   ├── tui_app.py              # LorneApp: layout IDE
│   ├── session_picker_screen.py  # Модальный выбор сессии при старте TUI
│   ├── tui_bridge.py           # Мост агент ↔ панели (потокобезопасно)
│   ├── themes.py               # Темы
│   ├── visualization.py        # Rich в classic-режиме
│   ├── graph_display.py        # Creator Mode (classic)
│   └── panels/                 # file_explorer, active_agents, workspace_center (чат + вкладки), code_editor, …
│
└── Terminal/                   # python -m Terminal — те же режимы, что у tca.py
    ├── cli.py
    └── runner.py
```

### Как работает агент

TCA построен на [LangGraph](https://github.com/langchain-ai/langgraph) — фреймворке для создания графов состояний поверх LangChain.

#### Граф выполнения

```
┌────────────┐     tool_calls?   ┌─────────┐
│    agent   │ ──── yes ────────▶│  tools  │
│(call_model)│ ◀─────────────────│(execute)│
└────────────┘                   └─────────┘
       │
       │ no tool_calls
       ▼
      END
```

1. **`call_model`** — отправляет историю сообщений в LLM, получает ответ. Перед отправкой вызывает `_sanitize_messages()` для исправления возможных повреждений истории. При ошибке провайдера автоматически повторяет запрос (до 2 раз).

2. **`should_continue`** — если в ответе есть `tool_calls`, переходит к узлу `tools`. Иначе — завершение (END).

3. **`execute_tools`** — выполняет вызванные инструменты (read-only параллельно в пуле потоков, если все вызовы из «безопасного» набора; иначе по очереди), формирует `ToolMessage` с результатами. Если провайдер не поддерживает `parallel_tool_calls` при `bind_tools`, выполняется повторная привязка без этого флага.

4. Цикл повторяется, пока модель не ответит текстом без tool_calls.

#### Поток данных одного хода

```
Пользователь вводит задачу
  │
  ▼
Планирование (build_plan) → plan_tool(action=save) → .tca/plan.json
  │
  ▼
HumanMessage добавляется в messages
  │
  ▼
app.stream(messages) запускает граф:
  │
  ├─ call_model → AIMessage(tool_calls=[edit_file, run_command])
  ├─ execute_tools → [ToolMessage(result1), ToolMessage(result2)]
  ├─ call_model → AIMessage(tool_calls=[plan_tool update])
  ├─ execute_tools → [ToolMessage(result)]
  ├─ call_model → AIMessage(content="Готово! Вот что я сделал...")
  └─ END
  │
  ▼
save_state(messages) → SQLite
```

### Система инструментов

Инструменты — `@tool` (LangChain). У модели — **компактные имена** (`plan_tool`, `git_ops`, `library_context`, …) плюс «атомарные» (`read_file`, `edit_file`, `web_search`, …). Подробная таблица и поля `action`: **[wiki/TOOLS.md](wiki/TOOLS.md)** и **[wiki/COMPACT_TOOLS.md](wiki/COMPACT_TOOLS.md)**.

Кратко:

| Группа | Примеры имён у модели |
|--------|------------------------|
| Файлы | `read_file`, `list_files`, `edit_file`, `write_file`, `replace_file_lines`, `insert_file_lines`, `search_in_files`, **`code_file_tool`** |
| План / мысли | **`plan_tool`**, **`reasoning_tool`** |
| Терминал / код | `run_command`, `code_interpreter` |
| Git / версии | **`git_ops`**, **`file_versions_tool`** |
| Веб / доки | `web_search`, `web_fetch`, **`library_context`** (в т.ч. `action=search` вместо отдельного get_documentation) |
| Office / OCR | `office_document_read`, **`docx_write_tool`**, `docx_document_advanced_ops`, **`docxedit_tool`**, **`ocr_tool`**, `pdf_styled_document_create`, `create_pdf` |
| Прочее | `rag_search`, `ask_user`, кастомные тулы |
| **Только TUI + режим Agent** | **`headless_browser`**, **`playwright_sync`** (Python — только при галочке в **Files → Settings**) |
| **Фон** | **`start_background_task`**, **`get_background_result`** — см. [BACKGROUND_AND_DEEP.md](wiki/BACKGROUND_AND_DEEP.md) |
| **Загрузки** | **`download_file`** — HTTP(S) в файл в рабочей области проекта, лимиты в схеме (`Agent/tools/download_tool.py`) |

Защита `run_command`: блокировка опасных команд; **опциональная** дедупликация повторов одной и той же команды — только если задано ненулевое `TCA_RUN_COMMAND_DEDUPE_S` (по умолчанию выключено). Снимки версий — перед правками файлов.

Детали фонового помощника и **Deep Solver** (`spawn_subagent` / `get_subagent_result`): **[wiki/BACKGROUND_AND_DEEP.md](wiki/BACKGROUND_AND_DEEP.md)**.

### Управление контекстом

LLM имеют ограниченное окно контекста. TCA управляет этим через:

- **Компактирование** (`compact_conversation`) — старые сообщения сжимаются в текстовое резюме, сохраняя последние 10–12 сообщений. При сжатии границы не разрывают группы tool_call/ToolMessage.
- **Авто-компактирование** — срабатывает автоматически при превышении 30 сообщений.
- **Усечение результатов** (`_truncate_result`) — большие ответы инструментов обрезаются (лимиты по инструментам: 2000–4000 символов).
- **Санитизация** (`_sanitize_messages`) — перед каждым вызовом LLM проверяет и исправляет историю: удаляет осиротевшие `ToolMessage`, добавляет заглушки для незавершённых `tool_calls`.

### Устойчивость к ошибкам

- **Ретраи провайдера** — при ошибках вроде «Provider returned error», «rate limit», «bad gateway» автоматический повтор с задержкой (до 2 попыток). OpenRouter перемаршрутизирует на другого провайдера.
- **Восстановление JSON** — сломанный JSON от маленьких моделей восстанавливается через `json-repair` и ручной парсинг.
- **Починка tool_calls** — если модель возвращает tool_calls как текст (JSON в content), TCA парсит их вручную.
- **Склейка контента** — если модель ломает многострочный код в JSON-аргументах, `_reconstruct_broken_content` собирает фрагменты обратно.
- **Нормализация кода** — если модель передаёт литералы `\n` вместо переносов строк, они конвертируются в реальные переводы.
- **Петли тулов** — при многократно одинаковых вызовах в историю может вставляться нudge «смени стратегию» (`web_search`, план, другой файл/команда), см. `message_utils.tool_repetition_loop_nudge`.

### Хранение данных

| Файл | Формат | Содержимое |
|---|---|---|
| `.tca/checkpoints.sqlite` | SQLite | Сессии: `sessions`, `checkpoints` (messages JSON), снимки для отката ходов (`turn_*`) |
| `.tca/versions.sqlite` | SQLite | Снимки файлов для отката |
| `.tca/plan.json` | JSON | Текущий план задачи (`planning_tool`) |
| `.tca/ui_settings.json` | JSON | Тема, плотность, подсветка; браузерные тулы; свои модели OpenRouter/Ollama; пресеты Ollama |
| `~/.tca_config.json` | JSON | Выбранная модель, настройки Creator и др. |

Файлы под `.tca/` создаются в рабочей директории проекта; глобальный конфиг — в домашнем каталоге.

---

## Разработка

### Установка для разработки

```bash
git clone https://github.com/your-repo/TCA.git
cd TCA
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
echo 'OPENROUTER_API_KEY=sk-or-v1-ваш_ключ' > Agent/.env
python tca.py
```

### Зависимости

```
python-dotenv    — загрузка .env файлов
json-repair      — восстановление сломанного JSON от LLM
langchain-core   — базовые абстракции (messages, tools)
langchain-openai — ChatOpenAI для работы с OpenRouter
langgraph        — граф состояний для agent loop
rich             — красивый терминальный вывод
gitpython        — интеграция с Git (авто-коммиты, rollback, история)
ddgs             — веб-поиск через DuckDuckGo
reportlab        — генерация PDF (опционально)
playwright       — Python API браузера в режиме Agent (после установки: `playwright install chromium`)
```

### Добавление нового инструмента

1. Создайте файл в `Agent/tools/`, например `my_tool.py`:

```python
from langchain_core.tools import tool

@tool
def my_tool(arg1: str, arg2: int = 10) -> dict:
    """Описание инструмента — агент увидит этот текст."""
    # Логика
    return {"ok": True, "result": "..."}
```

2. Экспортируйте из `Agent/tools/__init__.py`:

```python
from .my_tool import my_tool
# Добавьте в __all__
```

3. Добавьте в список `_base_tools` в `Agent/tool_registry.py`:

```python
_base_tools: List[Any] = [
    ...,
    my_tool,
]
```

4. Опционально: добавьте описание в системный промпт (`Agent/system_promt.py`) и специальный вывод в `Interface/visualization.py`.

### Добавление модели

Добавьте запись в `AVAILABLE_MODELS` в `Agent/llm_provider.py`:

```python
{"id": "provider/model-name", "name": "Display Name", "ctx": 128_000, "tier": "free|cheap|paid|pro"},
```

Если провайдер модели поддерживает `parallel_tool_calls`, добавьте его в `_PROVIDER_CAPS`.

### Ключевые модули для разработчика

| Модуль | Что менять |
|---|---|
| `Agent/agent/` | Точка входа TUI/classic, мост с UI, сессии |
| `Agent/graph_runner.py` | LangGraph: узлы и рёбра графа, подсказки при петлях |
| `Agent/tool_registry.py` | Список инструментов, `build_tools(agent_mode=...)` |
| `Agent/command_router/` | Slash-команды (classic) |
| `Agent/deep_solver/` | Режим Deep Solver (локальная модель), `legacy_loop.py` |
| `Agent/background_agent_runner.py` | Очередь фоновых микро-задач LLM+тулов |
| `Agent/message_utils/` | Санитизация, компактирование, восстановление tool JSON, анти-петля |
| `Agent/git_integration.py` | Git |
| `Agent/rag/` | RAG |
| `Agent/llm_provider.py` | Модели и OpenRouter |
| `Agent/system_promt.py` | Системный промпт |
| `Agent/tools/` | Реализации инструментов |
| `Interface/tui_app.py` | Layout IDE, CSS |
| `Interface/tui_bridge.py` | Обновление панелей из фонового агента |
| `Interface/panels/*.py` | Панели: дерево, агенты, чат, редактор, … |
| `Interface/visualization.py` | Вывод в classic-режиме |
| `Terminal/runner.py` | Shell-команды |

Полная таблица файлов — **[wiki/ARCHITECTURE.md](wiki/ARCHITECTURE.md)**.

---

## Удаление

**macOS / Linux:**

```bash
./uninstall.sh
```

**Windows:**

```cmd
uninstall.bat
```

Скрипт удалит виртуальное окружение и команды `lorne` / `tca` в PATH. Опционально удалит данные сессий и версий.

---

## Лицензия

MIT — см. [LICENSE](LICENSE).
