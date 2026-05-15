# Lorne v0.98 — терминальный ассистент для кода


![](./wiki/image.png)



**Документация:** [wiki/README.md](wiki/README.md) · [wiki/tutorials/quickstart.md](wiki/tutorials/quickstart.md) · [wiki/MODES/README.md](wiki/MODES/README.md) · [wiki/PROJECT_BRAIN.md](wiki/PROJECT_BRAIN.md) · [wiki/ARCHITECTURE.md](wiki/ARCHITECTURE.md) · [wiki/TOOLS.md](wiki/TOOLS.md) · [wiki/COMPACT_TOOLS.md](wiki/COMPACT_TOOLS.md) · [wiki/BACKGROUND_AND_DEEP.md](wiki/BACKGROUND_AND_DEEP.md) · [wiki/EXTENDING.md](wiki/EXTENDING.md) · [docs/README.md](docs/README.md)

---

Lorne — это **терминальный AI-ассистент для разработки**, который запускается прямо в папке вашего проекта, общается с LLM через [OpenRouter](https://openrouter.ai/) и умеет самостоятельно читать, писать и редактировать файлы, выполнять команды, работать с Git, искать по документации и проводить длительные многошаговые задачи.

Работает в двух режимах: **TUI-IDE** (Textual, по умолчанию) или **Classic** (чат в терминале через Rich).

---

## Возможности

### Работа с кодом и файлами
- **Файлы** — чтение (с пагинацией), создание, редактирование, поиск по содержимому
- **Терминал** — выполнение shell-команд с подтверждением пользователя
- **Git** — автокоммиты, откат к коммиту, просмотр истории и diff через GitPython
- **Версионирование** — SQLite-снимки файлов независимо от Git (откат отдельного файла или целого хода)
- **Офисные документы** — чтение/запись DOCX, создание PDF (ReportLab), OCR (pytesseract), чтение офисных форматов
- **Браузер** — `headless_browser` / `playwright_sync` (только в режиме Agent, включается в настройках)
- **Загрузки** — `download_file` скачивает файл по URL в рабочую директорию проекта

### Поиск и понимание проекта
- **RAG-поиск** — семантический чанкинг, word-level scoring, mtime-кэш, инкрементальная переиндексация
- **Project Brain** — автоматически формируемая Markdown-база знаний о проекте в каталоге `project_brain/`: обзор архитектуры, дерево модулей, описание потоков данных. Индексируется как RAG-источник с меткой `brain`. В режиме **Brainer** после каждого ответа агент обновляет brain.
- **Документация пакетов** — инструмент `library_context` (через Context7) загружает актуальную документацию прямо в контекст
- **Веб-поиск** — `web_search` + `web_fetch` через DuckDuckGo

### Режимы работы агента
Режим выбирается кнопками в TUI-панели чата (или автоматически через команды):

| Режим | Описание |
|-------|----------|
| **Normal** | Стандартный цикл: полный набор инструментов, планирование, выполнение |
| **Ask** | Только чтение и поиск — без редактирования файлов, без git, без терминала. Удобен для вопросов по коду |
| **Agent** | Расширенный набор инструментов: дополнительно браузер (`headless_browser`, `playwright_sync`) по настройке |
| **Research** | Акцент на веб-источники и документацию пакетов |
| **Creator** | Параллельное/последовательное выполнение подзадач несколькими LLM-воркерами |
| **Brainer** | Приоритет `rag_search` и `project_brain/` для глубокого понимания кодовой базы; после каждого ответа — автообновление brain |
| **Deep** | Длительный автономный цикл на **локальной** модели (Ollama и т.п.) с чекпоинтами и субагентами |

### Сессии и безопасность
- **Сессии** — сохранение и восстановление диалогов между запусками (SQLite), именованные чаты
- **Откат хода (TUI)** — кнопка у каждого сообщения: восстанавливает историю диалога и рабочие файлы до состояния перед этим ходом
- **Планирование** — автоматическое построение плана для сложных задач с отслеживанием прогресса
- **Управление контекстом** — авто-компактирование при превышении 30 сообщений, усечение длинных ответов инструментов

### Производительность
- **Параллельные инструменты** — read-only инструменты выполняются параллельно в пуле потоков
- **Фоновый помощник** — `start_background_task` / `get_background_result`: отдельный LLM-цикл в потоке, пока основной граф ждёт долгого `run_command`
- **Много моделей** — 27+ моделей через OpenRouter (бесплатные, дешёвые, платные, про)
- **Локальные модели** — доразбор `tool_calls`, восстановление JSON, извлечение `<thought>`, подсказки при шумных ответах

### Устойчивость
- **Ретраи провайдера** — при ошибках «Provider returned error», «rate limit», «bad gateway» — автоповтор с задержкой
- **Восстановление JSON** — сломанный ответ маленькой модели исправляется через `json-repair`
- **Антипетля** — при повторяющихся одинаковых вызовах инструментов в промпт вставляется подсказка сменить стратегию

---

## Быстрый старт

### Требования

- Python 3.10+
- API-ключ [OpenRouter](https://openrouter.ai/) (есть бесплатные модели)

### Установка

**macOS / Linux:**

```bash
git clone https://github.com/threenebula23/Lorne.git
cd Lorne
chmod +x install.sh
./install.sh
```

**Windows:**

```cmd
git clone https://github.com/threenebula23/Lorne.git
cd Lorne
install.bat
```

Скрипт установки:
1. Создаёт виртуальное окружение `.venv`
2. Устанавливает зависимости из `requirements.txt`
3. Создаёт команды **`lorne`** и **`tca`** (алиас) в PATH

### Первый запуск

```bash
# С ключом через аргумент (сохраняется в Agent/.env — повторно вводить не нужно)
lorne env=sk-or-v1-ваш_ключ

# Или записать ключ вручную
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
LORNE_MODE=classic lorne
# или
lorne --classic
python -m Terminal --classic
```

Явно включить TUI: `lorne --tui` или `LORNE_MODE=tui` (значение по умолчанию).

Альтернативный способ запуска (без установки):

```bash
python lorne.py
python -m Terminal              # TUI; для classic: python -m Terminal --classic
```

### Интерфейс

После запуска Lorne откроет окно выбора сессии (в TUI), затем главный экран. Слева — файловый проводник и панель активных агентов, в центре — панели чата и редактора с вкладками.

В панели чата доступен выбор **режима** (Normal / Ask / Agent / Research / Creator / Brainer / Deep) и **модели**.

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

В **TUI** при старте открывается модальное окно со списком чатов: заголовок, время обновления, примерное число сообщений. Доступны **Открыть**, **Удалить**, **Новый чат** и **Выход**.

В **classic**-режиме — текстовый выбор: **Enter** — новая сессия, **номер** — продолжить, **d номер** — удалить.

Сессии и история сообщений хранятся в **`.lorne/checkpoints.sqlite`** (если legacy `.tca/` не существует — создаётся `.lorne/`). Дополнительно для отката ходов ведутся снимки диалога и рабочей копии файлов на границе каждого пользовательского сообщения (таблицы `turn_snapshots`, `turn_workspace_snapshots`).

---

## Конфигурация

### API-ключ

Три способа указать ключ OpenRouter (в порядке приоритета):

1. **Аргумент запуска:** `lorne env=sk-or-v1-xxx` (сохраняется в `Agent/.env` автоматически)
2. **Файл `.env`:** создать `Agent/.env` или `.env` в корне с содержимым `OPENROUTER_API_KEY=sk-or-v1-xxx`
3. **Переменная окружения:** `export OPENROUTER_API_KEY=sk-or-v1-xxx`

### Профили

| Профиль | Temperature | Max tokens | Назначение |
|---|---|---|---|
| `fast` | 0.1 | 4096 | Быстрые простые задачи |
| `balanced` | 0.2 | 8192 | Баланс скорости и качества (по умолчанию) |
| `quality` | 0.1 | 16384 | Максимальное качество |

### Переменные окружения

Переменные поддерживают два префикса: **`LORNE_*`** (приоритет) и **`TCA_*`** (совместимость). Например, `LORNE_MODE=classic` или `TCA_MODE=classic` — оба работают.

| Переменная | Описание | По умолчанию |
|---|---|---|
| `OPENROUTER_API_KEY` | API-ключ OpenRouter | — (обязательно) |
| `LORNE_MODE` / `TCA_MODE` | `tui` (IDE) или `classic` (чат в терминале) | `tui` |
| `LORNE_PROFILE` / `TCA_PROFILE` | Профиль по умолчанию | `balanced` |
| `LORNE_MODEL` / `TCA_MODEL` | Модель по умолчанию | `arcee-ai/trinity-large-preview:free` |
| `LORNE_BASE_URL` / `TCA_BASE_URL` | Base URL для API | `https://openrouter.ai/api/v1` |
| `LORNE_MODEL_FAST` / `TCA_MODEL_FAST` | Модель для профиля fast | значение `*_MODEL` |
| `LORNE_MODEL_BALANCED` / `TCA_MODEL_BALANCED` | Модель для профиля balanced | значение `*_MODEL` |
| `LORNE_MODEL_QUALITY` / `TCA_MODEL_QUALITY` | Модель для профиля quality | значение `*_MODEL` |
| `LORNE_TEMP_FAST` / `TCA_TEMP_FAST` | Temperature для fast | `0.1` |
| `LORNE_TEMP_BALANCED` / `TCA_TEMP_BALANCED` | Temperature для balanced | `0.2` |
| `LORNE_TEMP_QUALITY` / `TCA_TEMP_QUALITY` | Temperature для quality | `0.1` |
| `LORNE_MAX_TOKENS` / `TCA_MAX_TOKENS` | Max tokens (глобально) | `8192` |
| `LORNE_MAX_TOKENS_FAST` / `TCA_MAX_TOKENS_FAST` | Max tokens для fast | `4096` |
| `LORNE_MAX_TOKENS_BALANCED` / `TCA_MAX_TOKENS_BALANCED` | Max tokens для balanced | `8192` |
| `LORNE_MAX_TOKENS_QUALITY` / `TCA_MAX_TOKENS_QUALITY` | Max tokens для quality | `16384` |
| `LORNE_RAG_PATTERNS` / `TCA_RAG_PATTERNS` | Паттерны для RAG-индексации | `*.py,*.md,*.ts,*.tsx,*.json` |
| `LORNE_RAG_MAX_FILES` / `TCA_RAG_MAX_FILES` | Макс. число файлов для RAG | `500` |
| `LORNE_RUN_COMMAND_DEDUPE_S` / `TCA_RUN_COMMAND_DEDUPE_S` | Окно анти-спама для повторной той же `run_command` (сек.); **0** = отключено | `0` |
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

Выбор модели сохраняется в `~/.lorne_config.json` между запусками.

---

## Архитектура

Подробная карта модулей, потоков данных и путей к SQLite — в **[wiki/ARCHITECTURE.md](wiki/ARCHITECTURE.md)**.

### Структура проекта (кратко)

```
Lorne/
├── lorne.py                    # Основная точка входа; после install — команда lorne (tca — алиас)
├── tca.py                      # Тонкая обёртка: from lorne import main
├── requirements.txt
├── wiki/                       # ARCHITECTURE.md, EXTENDING.md, TOOLS.md, BACKGROUND_AND_DEEP.md
│
├── Agent/                      # Ядро: LLM, LangGraph, инструменты, RAG, сессии
│   ├── agent/                  # run_tui_mode / run_coding_agent_loop; снимки, откат TUI
│   ├── graph_runner.py         # LangGraph: call_model, execute_tools, анти-петля
│   ├── tool_registry.py        # build_tools(agent_mode, ask_mode, playwright_python), compact + custom
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
│   ├── project_brain/          # Сканер и генератор Markdown-базы знаний о проекте
│   ├── prompts/                # Аддоны промпта для каждого режима (_MODE_ADDONS)
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
└── Terminal/                   # python -m Terminal — те же режимы, что у lorne.py
    ├── cli.py
    └── runner.py
```

### Как работает агент

Lorne построен на [LangGraph](https://github.com/langchain-ai/langgraph) — фреймворке для создания графов состояний поверх LangChain.

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

3. **`execute_tools`** — выполняет вызванные инструменты (read-only параллельно в пуле потоков, если все вызовы из «безопасного» набора; иначе по очереди), формирует `ToolMessage` с результатами.

4. Цикл повторяется, пока модель не ответит текстом без tool_calls.

#### Поток данных одного хода

```
Пользователь вводит задачу
  │
  ▼
Планирование (build_plan) → plan_tool(action=save) → .lorne/plan.json
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

### Project Brain

`project_brain/` в корне рабочего проекта — Markdown-база знаний о самом проекте: обзор архитектуры, дерево модулей, описание сервисов, потоки данных. Формируется автоматически сканером и дополняется агентом через `project_brain_tool`.

- **Сканер** перезаписывает корневые обзорные файлы (`overview.md`, `architecture.md`, `modules/…`).
- **Агент** пишет в разрешённые пути: `agent/**/*.md`, `*_notes.md`, `*_supplement.md`, `agent_architecture.md`.
- Индексируется как приоритетный RAG-источник с меткой `brain`.
- В режиме **Brainer** после каждого ответа выполняется полный `refresh_project_brain` + переиндексация.

Подробнее: **[wiki/PROJECT_BRAIN.md](wiki/PROJECT_BRAIN.md)**.

### Система инструментов

Инструменты — `@tool` (LangChain). У модели — **компактные имена** (`plan_tool`, `git_ops`, `library_context`, …) плюс «атомарные» (`read_file`, `edit_file`, `web_search`, …). Подробная таблица и поля `action`: **[wiki/TOOLS.md](wiki/TOOLS.md)** и **[wiki/COMPACT_TOOLS.md](wiki/COMPACT_TOOLS.md)**.

| Группа | Примеры имён у модели |
|--------|------------------------|
| Файлы | `read_file`, `list_files`, `edit_file`, `write_file`, `replace_file_lines`, `insert_file_lines`, `search_in_files`, **`code_file_tool`** |
| План / мысли | **`plan_tool`**, **`reasoning_tool`** |
| Терминал / код | `run_command`, `code_interpreter` |
| Git / версии | **`git_ops`**, **`file_versions_tool`** |
| Веб / доки | `web_search`, `web_fetch`, **`library_context`** |
| Office / OCR | `office_document_read`, **`docx_write_tool`**, `docx_document_advanced_ops`, **`docxedit_tool`**, **`ocr_tool`**, `pdf_styled_document_create`, `create_pdf` |
| Знания о проекте | **`project_brain_tool`** (`refresh` / `write_brain` / `write_architecture`), **`rag_search`** |
| Прочее | `ask_user`, кастомные тулы |
| **Только TUI + режим Agent** | **`headless_browser`**, **`playwright_sync`** (включается в Settings) |
| **Фон** | **`start_background_task`**, **`get_background_result`** — см. [BACKGROUND_AND_DEEP.md](wiki/BACKGROUND_AND_DEEP.md) |
| **Загрузки** | **`download_file`** — HTTP(S) в файл в рабочей области проекта |

В режиме **Ask** недоступны все мутирующие инструменты: `edit_file`, `write_file`, `run_command`, `git_ops`, `download_file` и другие. Полный список — [wiki/MODES/ask.md](wiki/MODES/ask.md).

### Управление контекстом

- **Компактирование** (`compact_conversation`) — старые сообщения сжимаются в текстовое резюме, сохраняя последние 10–12 сообщений. При сжатии не разрываются группы tool_call/ToolMessage.
- **Авто-компактирование** — срабатывает автоматически при превышении 30 сообщений.
- **Усечение результатов** (`_truncate_result`) — большие ответы инструментов обрезаются (лимиты 2000–4000 символов).
- **Санитизация** (`_sanitize_messages`) — перед каждым вызовом LLM проверяет и исправляет историю: удаляет осиротевшие `ToolMessage`, добавляет заглушки для незавершённых `tool_calls`.

### Хранение данных

Данные хранятся в каталоге проекта `.lorne/` (если существует legacy `.tca/` — используется он).

| Файл | Формат | Содержимое |
|---|---|---|
| `.lorne/checkpoints.sqlite` | SQLite | Сессии: `sessions`, `checkpoints` (messages JSON), снимки для отката ходов (`turn_*`) |
| `.lorne/versions.sqlite` | SQLite | Снимки файлов для отката |
| `.lorne/plan.json` | JSON | Текущий план задачи |
| `.lorne/ui_settings.json` | JSON | Тема, плотность, подсветка; браузерные тулы; свои модели OpenRouter/Ollama; пресеты Ollama |
| `~/.lorne_config.json` | JSON | Выбранная модель, настройки Creator и др. (глобально) |

Пути конфигурации: `Agent/runtime_paths.py` — сначала ищет `LORNE_*`, потом `TCA_*`; каталог данных — `.lorne` если нет legacy `.tca`.

---

## Разработка

### Установка для разработки

```bash
git clone https://github.com/threenebula23/Lorne.git
cd Lorne
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
echo 'OPENROUTER_API_KEY=sk-or-v1-ваш_ключ' > Agent/.env
python lorne.py
```

### Зависимости

```
python-dotenv      — загрузка .env файлов
json-repair        — восстановление сломанного JSON от LLM
langchain-core     — базовые абстракции (messages, tools)
langchain-openai   — ChatOpenAI для работы с OpenRouter
langgraph          — граф состояний для agent loop
rich               — красивый терминальный вывод (classic-режим)
textual            — TUI-IDE
gitpython          — интеграция с Git (автокоммиты, rollback, история)
ddgs               — веб-поиск через DuckDuckGo
reportlab          — генерация PDF
playwright         — браузер в режиме Agent (после установки: `playwright install chromium`)
python-docx        — чтение/запись DOCX
PyMuPDF            — чтение PDF
pytesseract        — OCR
```

### Добавление нового инструмента

1. Создайте файл в `Agent/tools/`, например `my_tool.py`:

```python
from langchain_core.tools import tool

@tool
def my_tool(arg1: str, arg2: int = 10) -> dict:
    """Описание инструмента — агент увидит этот текст."""
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

Подробно: **[wiki/developer/ADDING_TOOLS.md](wiki/developer/ADDING_TOOLS.md)**.

### Добавление модели

Добавьте запись в `AVAILABLE_MODELS` в `Agent/llm_provider.py`:

```python
{"id": "provider/model-name", "name": "Display Name", "ctx": 128_000, "tier": "free|cheap|paid|pro"},
```

Если провайдер поддерживает `parallel_tool_calls`, добавьте его в `_PROVIDER_CAPS`.

### Ключевые модули для разработчика

| Модуль | Что менять |
|---|---|
| `Agent/agent/` | Точка входа TUI/classic, мост с UI, сессии |
| `Agent/graph_runner.py` | LangGraph: узлы и рёбра графа, подсказки при петлях |
| `Agent/tool_registry.py` | Список инструментов, `build_tools(agent_mode=..., ask_mode=...)` |
| `Agent/prompts/` | Аддоны системного промпта для каждого режима |
| `Agent/command_router/` | Slash-команды (classic) |
| `Agent/deep_solver/` | Режим Deep Solver (локальная модель) |
| `Agent/background_agent_runner.py` | Очередь фоновых микро-задач LLM+тулов |
| `Agent/message_utils/` | Санитизация, компактирование, восстановление tool JSON, антипетля |
| `Agent/project_brain/` | Сканер и генератор Markdown-базы знаний |
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
