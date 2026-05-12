# Интерфейс TUI — обзор компонентов

## Слои

1. **Приложение** — `Interface/tui_app.py` (`LorneApp`): композиция виджетов, биндинги клавиш, обработка `ChatSubmitted`, открытие файлов.
2. **Мост** — `Interface/tui_bridge.py`: безопасные вызовы из фонового потока агента в главный поток Textual (`call_from_thread`).
3. **Панели** — `Interface/panels/`:
   - `ai_chat/` — лента сообщений, ввод, режим, модель;
   - `workspace_center.py` — вкладки;
   - `file_explorer.py` — дерево проекта и **вкладки настроек**;
   - `active_agents_panel.py` — Creator;
   - `code_editor/`, `image_viewer.py`, и др.

## Поток сообщения чата

`AIChatPanel` → событие → callback из `Agent/agent` (сборка сообщения, запуск графа в потоке) → ответы через `TUIBridge` обратно в панель.

## Расширение

См. [EXTENDING.md](EXTENDING.md) в этой папке и [../developer/ADDING_TOOLS.md](../developer/ADDING_TOOLS.md) для тулов.

Настройки и prefs: [SETTINGS.md](SETTINGS.md).
