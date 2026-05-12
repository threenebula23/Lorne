# Режим: creator

## Реализация

- Оркестрация: `Agent/creator_mode.py`, `Agent/creator_orchestration.py`; UI — дерево воркеров в `ActiveAgentsPanel`.
- В TUI `creator` включает `agent_mode=True` для набора тулов (браузер по prefs), см. `_sync_tui_tool_bundle("creator")`.
- Параллельность и стратегия: prefs `orchestration_mode`, `orchestration_max_workers` в `Interface/ui_prefs.py`.

## Схема потока

```mermaid
flowchart TB
  user[User] --> creator[Creator_orchestrator]
  creator --> w1[Worker_1_graph]
  creator --> w2[Worker_2_graph]
  w1 --> tools[Same_tool_names]
  w2 --> tools
```

## Инструменты

Те же имена тулов, что у основного агента в режиме Agent (включая компактные). Воркеры не должны конфликтовать по одним и тем же путям — следует промпту режима в `_MODE_ADDONS["creator"]`.
