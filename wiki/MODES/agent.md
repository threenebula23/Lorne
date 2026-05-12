# Режим: agent

## Реализация

- Системное дополнение: `Agent/prompts/__init__.py`, ключ `"agent"`.
- Тулы: `build_tools(agent_mode=True, …)` в `Agent/tool_registry.py`; в TUI вызывается `_sync_tui_tool_bundle("agent")` в `Agent/agent/_impl_prepare.py`.
- При `agent_mode=True`: при prefs добавляются `headless_browser` и опционально `playwright_sync`.

## Схема потока

```mermaid
flowchart LR
  userNode[User] --> inputNode[AIChatPanel]
  inputNode --> appNode[LorneApp]
  appNode --> threadNode[Agent thread]
  threadNode --> langGraphNode[LangGraph]
  langGraphNode --> llmNode[LLM and tools]
  llmNode --> toolsNode[Tool invocations]
  toolsNode --> fsNode[Workspace FS]
```

## Инструменты

Полный набор `_base_tools` плюс браузерные при включённых настройках. См. [TOOLS.md](../TOOLS.md).

Переключатель **Custom tools** отключает группу: `rag_search`, `plan_tool`, `reasoning_tool`, `code_interpreter`, `library_context`, `file_versions_tool`, `project_brain_tool` (`_CUSTOM_TOOL_NAMES` в `Agent/tool_registry.py`).
