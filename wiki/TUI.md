# TUI — обзор

Textual-приложение: выбор сессии → главное окно с чатом и файлами.

## Компоненты

1. **`Interface/session_picker_screen.py`** — список чатов, новый чат, выход.
2. **`Interface/tui_app.py`** (`LorneApp`) — сетка: `Header`, слева `FileExplorerPanel` + `ActiveAgentsPanel`, центр `WorkspaceCenter`.
3. **`Interface/panels/workspace_center.py`** — вкладки: чат (`ai_chat`) и открытые файлы/изображения.
4. **`Interface/panels/ai_chat/`** — сообщения, выбор модели и **режима** (Normal, Creator, Agent, Research, …), отправка.
5. **`Interface/tui_bridge.py`** — колбэки из потока агента в UI через `call_from_thread`.

Режимы и тулы: [MODES/README.md](MODES/README.md). Настройки: [Interface/SETTINGS.md](Interface/SETTINGS.md).

## Стили

Классы плотности `density-compact|normal|spacious` на приложении; TCSS в `Interface/tui_app.tcss`. Подробнее: [Interface/STYLING.md](Interface/STYLING.md).
