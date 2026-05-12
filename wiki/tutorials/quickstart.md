# Быстрый старт

## Требования

- Python 3.10+ (см. `requirements.txt` в корне репозитория).
- Ключ **OpenRouter** для облачных моделей (или локальная Ollama — см. README).

## Установка

Из корня репозитория:

```bash
chmod +x install.sh && ./install.sh
```

Скрипт создаёт venv (если нужно), ставит зависимости, добавляет команды `lorne` и `tca` в PATH активированного окружения.

## Запуск

```bash
lorne                    # TUI в текущей директории
lorne /path/to/project   # смена корня проекта
lorne env=sk-or-v1-KEY   # ключ OpenRouter в env на сессию
```

Алиас: **`tca`** — то же самое. Устаревшая точка входа: **`python tca.py`** → делегирует в `lorne.main`.

Classic CLI (без полного TUI IDE):

```bash
lorne --classic
# или
LORNE_MODE=classic lorne
```

Модуль: `python -m Terminal` (см. `Terminal/cli.py`).

## Переменные окружения

Префиксы **`LORNE_`** и **`TCA_`** (совместимость): см. `Agent/runtime_paths.py` (`env_pref`).

Примеры: `LORNE_MODE`, `OPENROUTER_API_KEY` в `Agent/.env`.

## Дальше

- [Индекс wiki](../README.md)
- [Архитектура](../ARCHITECTURE.md)
- [Режимы](../MODES/README.md)
