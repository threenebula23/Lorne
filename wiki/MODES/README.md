# Режимы TUI

Каждый режим задаёт дополнительный фрагмент системного промпта (`Agent/prompts/__init__.py`, `_MODE_ADDONS`) и влияет на набор тулов через `_sync_tui_tool_bundle` / `build_tools` в `Agent/agent/_impl_prepare.py`.

| Режим | Файл | Кратко |
|-------|------|--------|
| Ask | [ask.md](ask.md) | Только чтение и поиск, без мутаций и без части тулов |
| Agent | [agent.md](agent.md) | Полный цикл, опционально браузер |
| Creator | [creator.md](creator.md) | Параллельные воркеры, те же туловые имена |
| Research | [research.md](research.md) | Акцент на веб и документацию пакетов |
| Deep | [deep.md](deep.md) | Отдельный долгий локальный цикл (не граф чата) |
| Brainer | [brainer.md](brainer.md) | Project Brain и RAG в приоритете |

Общий обзор UI: [TUI.md](../TUI.md). Архитектура: [ARCHITECTURE.md](../ARCHITECTURE.md).
