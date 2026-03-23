# TCA — Terminal Coding Assistant


```
                                                       
                                                       
                           =====                       
                  ......  ==-***===                    
                ...++++. ==**--****==                  
                .+*%%%%*.=**%%%%%%%*==                 
               .+%%%%%%%*=*%%%***#%%**=                
              .*%%%%##%%%=*%%%%%%%%#%**=               
             .+%%%#===#%%**%%%**+*%%*%#*=              
             .*%%#=###=#%%*%*%*:::+*%#%*=            d888888888b.   .d8888b.        d8888 
            .=%%#=##==#*#%%%%%+::::+%%%%*=               888       d88P  Y88b      d88888 
            .*%%=##====*#%%%%%*+:::+*%#%*=               888       888            d888888
            .*%%=#==  ==##%%%%%*+++**%*%*==              888       888           d88P 888
             *%###=    ==#*%%%%%%%*%%%#%*-=              888       888          d88P  888
            .%%##==    =##*%%%%#*%%%*#%%*=               888       Y88b  d88P  d888888888
            .%%###=   ==#=#%%**%%%%%%%#**=               888        "Y8888P"  d88P    888
            .*%#=#== ===#=%%%+=*********==              
            .*%%=#=====#==%%* .=========               
             *%%-=#===##=#%%+.                          
            .+*%%-=####=-%%*..                          
             .*%%%-===--%#%+.                           
              .*%%%#-##%%%*.                            
              .+*% %%%%%%* .                            
               .=*%%%%%** .                             
                . +***++..                              
                 . .....                                
                                                       
                                                       
```



Терминальный ассистент кодинга на базе LLM. Работает в любом проекте прямо из консоли: читает, пишет и редактирует файлы, выполняет команды, строит планы и ведёт историю изменений с возможностью отката. Вдохновлён Claude Code.

**Документация для разработчиков (модули, архитектура):** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/EXTENDING.md](docs/EXTENDING.md) · [docs/TOOLS.md](docs/TOOLS.md) · [docs/README.md](docs/README.md)

## Возможности

- **Работа с файлами** — чтение (с пагинацией), создание, редактирование, поиск по содержимому
- **Терминал** — выполнение shell-команд с подтверждением пользователя
- **Планирование** — автоматическое построение плана для сложных задач с отслеживанием прогресса
- **Версионирование** — SQLite-снимки файлов + Git-интеграция (автокоммиты, откат, история)
- **RAG-поиск** — семантический чанкинг, word-level scoring, mtime-кэш, инкрементальная переиндексация
- **Сессии** — сохранение и восстановление диалогов между запусками (SQLite)
- **Красивый UI** — Rich-панели, подсветка синтаксиса, прогресс-бары, Markdown, подсказки команд
- **Много моделей** — 27+ моделей через OpenRouter (бесплатные, дешёвые, платные, про)
- **Creator Mode** — параллельное выполнение подзадач несколькими агентами (local + heavy модели)
- **Параллельные инструменты** — read-only инструменты выполняются параллельно для ускорения
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
3. Создаёт команду `tca`, доступную из любой директории

### Первый запуск

```bash
# С ключом через аргумент
tca env=sk-or-v1-ваш_ключ

# Или сохранить ключ в файл
echo 'OPENROUTER_API_KEY=sk-or-v1-ваш_ключ' > Agent/.env
tca
```

---

## Использование

### Запуск

```bash
tca                            # работает в текущей директории
tca /path/to/project           # работает в указанном проекте
tca env=sk-or-v1-xxx           # передать API-ключ через аргумент
tca /path/to/project env=KEY   # оба варианта (любой порядок)
```

По умолчанию запускается **TUI-IDE** (Textual). Классический режим только с чатом в терминале:

```bash
TCA_MODE=classic tca
# или
tca --classic
```

Альтернативный способ запуска (без установки):

```bash
python tca.py
python -m Terminal
```

### Интерфейс

После запуска TCA покажет приветственный экран с текущей моделью, профилем и проектом. Далее — интерактивный цикл ввода задач.

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
| `/rollback <файл> [id]` | Откатить файл к предыдущей версии (SQLite) |
| `/git status` | Статус Git-репозитория |
| `/git log [файл]` | История Git-коммитов |
| `/git diff [хеш]` | Git diff текущих изменений или коммита |
| `/git rollback <хеш>` | Откатить Git-коммит (revert) |
| `/compact` | Сжать историю разговора (освободить контекст) |
| `/creator` | Включить/выключить Creator Mode (параллельные агенты) |
| `/creator <задача>` | Запустить задачу в Creator Mode |
| `/custom` | Управление кастомными инструментами |
| `/agent list` | Список логических под-агентов |
| `/help` | Справка по командам |
| `/exit` | Выйти |

### Сессии

При запуске TCA показывает список сохранённых сессий. Можно:

- Нажать **Enter** — создать новую сессию
- Ввести **номер** — продолжить существующую
- Ввести **d номер** — удалить сессию

Сессии сохраняются автоматически в `.tca_checkpoints.sqlite` в рабочей директории.

---

## Конфигурация

### API-ключ

Три способа указать ключ OpenRouter (в порядке приоритета):

1. **Аргумент запуска:** `tca env=sk-or-v1-xxx`
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

Подробная карта модулей, потоков данных и путей к SQLite — в **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

### Структура проекта (кратко)

```
TCA/
├── tca.py                      # Точка входа: TUI (по умолчанию) или classic CLI
├── requirements.txt
├── docs/                       # ARCHITECTURE.md, EXTENDING.md, TOOLS.md
│
├── Agent/                      # Ядро: LLM, LangGraph, инструменты, RAG, сессии
│   ├── agent.py                # run_tui_mode / run_coding_agent_loop
│   ├── graph_runner.py         # LangGraph: call_model, execute_tools
│   ├── tool_registry.py        # build_tools(), _base_tools + custom + agent_mode
│   ├── message_utils.py        # Санитизация, компактирование истории
│   ├── command_router.py       # Slash-команды в classic-режиме
│   ├── llm_provider.py         # OpenRouter, профили, модели
│   ├── planner.py              # Планы задач
│   ├── git_integration.py      # GitPython
│   ├── creator_mode.py         # Параллельные воркеры
│   ├── creator_provider.py
│   ├── system_promt.py         # Системный промпт
│   ├── tools/                  # @tool: файлы, терминал, git, web, RAG, PDF, ...
│   ├── rag/                    # Индексация и rag_search
│   ├── checkpoint/             # Сессии (SQLite)
│   ├── versioning/             # Снимки файлов (SQLite)
│   └── file_loading/           # Загрузка файлов для RAG
│
├── Interface/                  # TUI (Textual) + Rich для classic
│   ├── tui_app.py              # TCAApp: layout IDE
│   ├── tui_bridge.py           # Мост агент ↔ панели (потокобезопасно)
│   ├── themes.py               # Темы
│   ├── visualization.py        # Rich в classic-режиме
│   ├── graph_display.py        # Creator Mode (classic)
│   └── panels/                 # file_explorer, code_editor, ai_chat, terminal, version_control
│
└── Terminal/                   # python -m Terminal, runner shell
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

3. **`execute_tools`** — выполняет вызванные инструменты (read-only параллельно, write последовательно), формирует `ToolMessage` с результатами.

4. Цикл повторяется, пока модель не ответит текстом без tool_calls.

#### Поток данных одного хода

```
Пользователь вводит задачу
  │
  ▼
Планирование (build_plan) → save_plan() → plan.json
  │
  ▼
HumanMessage добавляется в messages
  │
  ▼
app.stream(messages) запускает граф:
  │
  ├─ call_model → AIMessage(tool_calls=[edit_file, run_command])
  ├─ execute_tools → [ToolMessage(result1), ToolMessage(result2)]
  ├─ call_model → AIMessage(tool_calls=[update_plan])
  ├─ execute_tools → [ToolMessage(result)]
  ├─ call_model → AIMessage(content="Готово! Вот что я сделал...")
  └─ END
  │
  ▼
save_state(messages) → SQLite
```

### Система инструментов

Все инструменты — функции с декоратором `@tool` из LangChain. Агент видит их описания и вызывает по необходимости.

#### Файловые операции

| Инструмент | Описание |
|---|---|
| `read_file(filename, offset, limit)` | Читает файл (с пагинацией для больших файлов) |
| `list_files(path, recursive, pattern)` | Список файлов/директорий с поддержкой glob |
| `search_in_files(directory, query, file_pattern)` | Полнотекстовый поиск по файлам |
| `edit_file(path, old_str, new_str)` | Замена подстроки в файле (с автоматическим снимком) |
| `write_file(path, content)` | Полная перезапись файла |
| `create_code_file(filepath, language, code)` | Создание файла с автоподбором расширения по языку |
| `append_code_snippet(filepath, snippet, language)` | Добавление кода в конец файла |
| `get_file_line_count(path)` | Число строк в файле |

#### Терминал

| Инструмент | Описание |
|---|---|
| `run_command(command, cwd, timeout_seconds)` | Выполнение shell-команды с подтверждением пользователя |

Защита: блокировка опасных команд (`rm -rf`, `mkfs`, ...), дедупликация повторных запусков в окне 20 секунд.

#### Планирование

| Инструмент | Описание |
|---|---|
| `save_plan(title, steps)` | Сохранить план (сохраняет статусы при перезаписи) |
| `load_plan()` | Загрузить текущий план |
| `update_plan(step_index, status, note)` | Обновить статус шага: `pending` → `in_progress` → `completed` / `blocked` |
| `clear_plan()` | Удалить план (с подтверждением) |

#### Версионирование

| Инструмент | Описание |
|---|---|
| `list_file_versions(path, limit)` | История снимков файла |
| `rollback_file(path, version_id)` | Откат к конкретной или последней версии |

Снимки создаются автоматически перед каждой операцией записи/редактирования.

#### Git

| Инструмент | Описание |
|---|---|
| `git_log(path, limit)` | История коммитов (по файлу или всему проекту) |
| `git_diff(commit)` | Diff коммита или текущих изменений |
| `git_rollback_file(path, commit)` | Откат файла к конкретному коммиту |
| `git_status()` | Текущий статус Git-репозитория |

#### Прочие

| Инструмент | Описание |
|---|---|
| `rag_search(query, top_k)` | Поиск по проекту с чанкингом и ранжированием |
| `ask_user(question)` | Задать вопрос пользователю в терминале |
| `create_pdf(filepath, title, body)` | Создать PDF-документ |

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

### Хранение данных

| Файл | Формат | Содержимое |
|---|---|---|
| `.tca_checkpoints.sqlite` | SQLite | Сессии (messages JSON) |
| `.tca_versions.sqlite` | SQLite | Снимки файлов для отката |
| `.tca_plan.json` | JSON | Текущий план задачи |
| `~/.tca_config.json` | JSON | Выбранная модель |

Все файлы создаются в рабочей директории проекта (кроме конфига модели в `~`).

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
| `Agent/agent.py` | Точка входа TUI/classic, мост с UI, сессии |
| `Agent/graph_runner.py` | LangGraph: узлы и рёбра графа |
| `Agent/tool_registry.py` | Список инструментов, `build_tools(agent_mode=...)` |
| `Agent/command_router.py` | Slash-команды (classic) |
| `Agent/message_utils.py` | Санитизация, компактирование истории |
| `Agent/git_integration.py` | Git |
| `Agent/rag/` | RAG |
| `Agent/llm_provider.py` | Модели и OpenRouter |
| `Agent/system_promt.py` | Системный промпт |
| `Agent/tools/` | Реализации инструментов |
| `Interface/tui_app.py` | Layout IDE, CSS |
| `Interface/tui_bridge.py` | Обновление панелей из фонового агента |
| `Interface/panels/*.py` | Отдельные панели (редактор, чат, git, …) |
| `Interface/visualization.py` | Вывод в classic-режиме |
| `Terminal/runner.py` | Shell-команды |

Полная таблица файлов — **[docs/ARCHITECTURE.md](wiki/ARCHITECTURE.md)**.

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

Скрипт удалит виртуальное окружение и команду `tca`. Опционально удалит данные сессий и версий.

---

## Лицензия

MIT — см. [LICENSE](LICENSE).
