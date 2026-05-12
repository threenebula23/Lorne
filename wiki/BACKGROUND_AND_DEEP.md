# Фоновые задачи и Deep Solver (обзор)

## Фоновый помощник

- Тулы: `start_background_task`, `get_background_result` (`Agent/tools/parallel_helper_tool.py`).
- Отдельный поток с собственным циклом LLM + tools; результат по токену.

## Deep Solver

Долгий **локальный** автономный цикл: не обычный чат-граф; реализация в `Agent/deep_solver/` (см. `legacy_loop.py`). Чекпойнты, очередь сообщений пользователя во время прогона, субагенты Creator через `spawn_subagent` / `get_subagent_result`.

**Детали режима, переменные окружения, чекпойнты:** [MODES/deep.md](MODES/deep.md).

## Связанные документы

- [MODES/README.md](MODES/README.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
