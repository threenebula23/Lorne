# Расширение TCA

Руководство по добавлению своих инструментов, моделей и настройке Creator Mode.

**Карта модулей и архитектура:** [ARCHITECTURE.md](ARCHITECTURE.md)

## Свой инструмент через CLI

Самый быстрый способ:

```bash
tca
❯ /custom add my_tool
```

Шаблон создаётся в `~/.tca_custom_tools/my_tool.py`. Отредактируйте файл и перезагрузите:

```bash
❯ /custom reload
```

## Свой инструмент через код

### 1. Файл инструмента

Создайте `Agent/tools/my_tool.py`:

```python
from typing import Dict, Any
from langchain_core.tools import tool

@tool
def my_awesome_tool(query: str, limit: int = 10) -> Dict[str, Any]:
    """Описание для модели: параметры и что возвращает функция."""
    results = do_something(query, limit)
    return {"ok": True, "results": results, "count": len(results)}
```

### 2. Экспорт в `__init__.py`

В `Agent/tools/__init__.py`:

```python
from .my_tool import my_awesome_tool
```

И добавьте имя в `__all__`.

### 3. Регистрация в `tool_registry.py`

В список `_base_tools` в `Agent/tool_registry.py`:

```python
_base_tools: List[Any] = [
    # ... существующие ...
    my_awesome_tool,
]
```

### 4. (Опционально) Системный промпт

В `Agent/system_promt.py` опишите, когда вызывать инструмент:

```
### Моя категория
- my_awesome_tool(query, limit) → что делает.
```

### 5. (Опционально) Вывод в classic-режиме

В `Interface/visualization.py` в `display_tool_result()`:

```python
if name == "my_awesome_tool" and isinstance(result, dict):
    _display_my_tool_result(result)
    return
```

## Новая модель

Добавьте запись в `AVAILABLE_MODELS` в `Agent/llm_provider.py`:

```python
{"id": "provider/model-name", "name": "Отображаемое имя", "ctx": 128_000, "tier": "free"},
```

Уровни (`tier`): `free`, `cheap`, `paid`, `pro`.

Если у провайдера есть `parallel_tool_calls`, добавьте в `_PROVIDER_CAPS`:

```python
"provider/": {"parallel_tool_calls": True, "native_tools": True},
```

## Creator Mode

Параллельное выполнение подзадач несколькими агентами.

### Настройка

1. Локальный сервер моделей (Ollama, LM Studio, vLLM):

```bash
ollama serve
ollama pull qwen3.5:27b
```

2. Параметры TCA:

```bash
tca
❯ /creator set local_base_url http://localhost:11434/v1
❯ /creator set local_model qwen3.5:27b
❯ /creator set max_workers 4
```

3. Включение и задача:

```bash
❯ /creator on
❯ Создай REST API с авторизацией, тестами и документацией
```

### Как устроено

1. **Планирование** — задача делится на подзадачи через LLM.
2. **Маршрутизация** — подзадача помечается как `simple` или `complex`.
   - Простые → локальная модель (быстро).
   - Сложные → тяжёлая модель (OpenRouter).
3. **Выполнение** — параллельно через `ThreadPoolExecutor`.
4. **Интерфейс** — прогресс воркеров (в classic — `graph_display`).

### Параметры

| Параметр | Описание | По умолчанию |
|----------|----------|----------------|
| `local_base_url` | URL OpenAI-совместимого API | `http://192.168.1.20:3000/api` |
| `local_model` | Имя модели на сервере | `qwen3.5:27b` |
| `max_workers` | Макс. параллельных агентов | `4` |

## Схема classic-режима (обзор)

```
Ввод пользователя
    │
    ▼
CommandRouter ──── slash-команды ──── прямой ответ
    │
    │ (обычный ввод)
    ▼
Planner ──── build_plan() ──── save_plan()
    │
    ▼
AgentGraph.stream()
    │
    ├── call_model (вызов LLM с retry)
    │   └── sanitize_messages → llm_with_tools.invoke()
    │
    ├── execute_tools (read-only параллельно, write по очереди)
    │   ├── read_file, list_files, search_in_files (параллельно)
    │   └── edit_file, write_file, run_command (последовательно)
    │
    └── should_continue → END, если нет tool_calls
```
