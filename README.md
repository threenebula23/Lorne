# TCA — Terminal Coding Assistant

Терминальный ассистент кодинга на базе LLM. Работает в любом проекте прямо из консоли: читает, пишет и редактирует файлы, выполняет команды, строит планы и ведёт историю изменений с возможностью отката. Вдохновлён Claude Code.

## Возможности

- **Работа с файлами** — чтение, создание, редактирование, поиск по содержимому
- **Терминал** — выполнение shell-команд с подтверждением пользователя
- **Планирование** — автоматическое построение плана для сложных задач с отслеживанием прогресса
- **Версионирование** — снимки файлов перед каждым изменением, откат к любой версии
- **RAG-поиск** — индексирование файлов проекта и поиск по ним
- **Сессии** — сохранение и восстановление диалогов между запусками (SQLite)
- **Красивый UI** — Rich-панели, подсветка синтаксиса, прогресс-бары, Markdown
- **Много моделей** — 18+ моделей через OpenRouter (бесплатные, дешёвые, платные)
- **Генерация PDF** — создание документов через ReportLab

---

## Быстрый старт

### Требования

- Python 3.10+
- API-ключ [OpenRouter](https://openrouter.ai/) (есть бесплатные модели)

### Установка

**macOS / Linux:**

```bash
git clone https://github.com/your-repo/TCA.git
cd TCA
chmod +x install.sh
./install.sh
```

**Windows:**

```cmd
git clone https://github.com/your-repo/TCA.git
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
| `/plan` | Показать текущий план задачи |
| `/status` | Информация о модели, контексте, сообщениях |
| `/ls [путь]` | Список файлов в директории |
| `/tree [путь]` | Дерево проекта |
| `/versions <файл>` | История версий файла |
| `/rollback <файл> [id]` | Откатить файл к предыдущей версии |
| `/compact` | Сжать историю разговора (освободить контекст) |
| `/agent list` | Список логических под-агентов |
| `/agent use <id>` | Переключить под-агент |
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
| `TCA_MODEL` | Модель по умолчанию | `meta-llama/llama-3.1-8b-instruct` |
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

### Доступные модели

Команда `/model` показывает полный список. Краткая сводка:

**Бесплатные:**
Llama 3.1 8B, Llama 3.3 70B, Llama 4 Scout, Llama 4 Maverick, Qwen 2.5 Coder 32B, Gemma 3 27B

**Дешёвые:**
DeepSeek V3, DeepSeek R1, QwQ 32B, Gemini 2.5 Flash, GPT-4o Mini, GPT-4.1 Mini/Nano, Claude 3.5 Haiku

**Платные:**
GPT-4o, GPT-4.1, Gemini 2.5 Pro, Claude Sonnet 4, Claude 3.5 Sonnet, Mistral Large

Выбор модели сохраняется в `~/.tca_config.json` между запусками.

---

## Архитектура

### Структура проекта

```
TCA/
├── tca.py                    # Главная точка входа (команда tca)
├── requirements.txt          # Зависимости
├── install.sh / install.bat  # Скрипты установки
├── uninstall.sh / .bat       # Скрипты удаления
│
├── Agent/                    # Ядро агента
│   ├── agent.py              # LangGraph-петля: call_model → execute_tools → should_continue
│   ├── llm_provider.py       # Управление моделями, профили, OpenRouter API
│   ├── system_promt.py       # Системный промпт с правилами и описанием инструментов
│   ├── planner.py            # Генерация планов задач через LLM
│   ├── path_utils.py         # Утилита разрешения путей
│   ├── multiagent.py         # Логические под-агенты (потоки работы)
│   ├── .env                  # API-ключ (не в git)
│   │
│   ├── tools/                # Инструменты агента (LangChain @tool)
│   │   ├── file_ops.py       # read_file, list_files, edit_file, write_file, search_in_files
│   │   ├── code_gen.py       # create_code_file, append_code_snippet
│   │   ├── terminal_tool.py  # run_command (с подтверждением пользователя)
│   │   ├── planning_tool.py  # save_plan, load_plan, update_plan, clear_plan
│   │   ├── versioning_tool.py# list_file_versions, rollback_file
│   │   ├── interactive.py    # ask_user
│   │   └── pdf_tool.py       # create_pdf
│   │
│   ├── checkpoint/           # Персистентность сессий (SQLite)
│   ├── versioning/           # Снимки файлов для отката (SQLite)
│   ├── rag/                  # RAG-индексирование и поиск
│   └── file_loading/         # Загрузка файлов для RAG
│
├── Interface/                # Терминальный UI
│   ├── visualization.py      # Rich-вывод: панели, таблицы, Markdown, прогресс-бары
│   └── path_loading.py       # Разрешение путей, выбор директории
│
└── Terminal/                 # Модуль запуска и выполнения команд
    ├── __main__.py           # python -m Terminal
    ├── cli.py                # Альтернативная точка входа
    └── runner.py             # Кросс-платформенное выполнение shell-команд
```

### Как работает агент

TCA построен на [LangGraph](https://github.com/langchain-ai/langgraph) — фреймворке для создания графов состояний поверх LangChain.

#### Граф выполнения

```
┌─────────┐     tool_calls?     ┌──────────┐
│  agent   │ ──── yes ────────▶ │  tools   │
│(call_model)│ ◀─────────────── │(execute) │
└─────────┘                     └──────────┘
     │
     │ no tool_calls
     ▼
    END
```

1. **`call_model`** — отправляет историю сообщений в LLM, получает ответ. Перед отправкой вызывает `_sanitize_messages()` для исправления возможных повреждений истории. При ошибке провайдера автоматически повторяет запрос (до 2 раз).

2. **`should_continue`** — если в ответе есть `tool_calls`, переходит к узлу `tools`. Иначе — завершение (END).

3. **`execute_tools`** — последовательно выполняет все вызванные инструменты, формирует `ToolMessage` с результатами.

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
| `read_file(filename)` | Читает файл, возвращает содержимое и число строк |
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

#### Прочие

| Инструмент | Описание |
|---|---|
| `rag_search(query, top_k)` | Поиск по индексированным файлам проекта |
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

3. Добавьте в список `tools` в `Agent/agent.py`:

```python
tools = [
    ...,
    my_tool,
]
```

4. Опционально: добавьте описание в системный промпт (`Agent/system_promt.py`) и специальный вывод в `Interface/visualization.py`.

### Добавление модели

Добавьте запись в `AVAILABLE_MODELS` в `Agent/llm_provider.py`:

```python
{"id": "provider/model-name", "name": "Display Name", "ctx": 128_000, "tier": "free|cheap|paid"},
```

Если провайдер модели поддерживает `parallel_tool_calls`, добавьте его в `_PROVIDER_CAPS`.

### Ключевые модули для разработчика

| Модуль | Что менять |
|---|---|
| `Agent/agent.py` | Логика агента, обработка ошибок, компактирование |
| `Agent/llm_provider.py` | Модели, профили, провайдеры |
| `Agent/system_promt.py` | Системный промпт (поведение агента) |
| `Agent/tools/` | Инструменты, доступные агенту |
| `Interface/visualization.py` | Отображение в терминале |
| `Terminal/runner.py` | Выполнение shell-команд |

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

Copyright (c) 2026 Даниил Асташёнок
