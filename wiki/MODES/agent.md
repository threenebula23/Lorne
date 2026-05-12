# Режим: agent

## Реализация

- Системное дополнение: `Agent/prompts/__init__.py`, ключ `"agent"`.
- Тулы: `build_tools(agent_mode=True, …)` в `Agent/tool_registry.py`; в TUI вызывается `_sync_tui_tool_bundle("agent")` в `Agent/agent/_impl_prepare.py`.
- При `agent_mode=True`: при prefs добавляются `headless_browser` и опционально `playwright_sync`.

## Схема потока

```mermaid
flowchart LR
  user[User] --> input[AIChatPanel]
  input --> app[LorneApp]
  app --> thread[Agent_thread]
  thread --> graph[LangGraph_runner]
  graph --> llm[LLM_bind_tools]
  llm --> tools[Tools_invoke]
  tools --> fs[Workspace_FS]
```

## Инструменты

Полный набор `_base_tools` плюс браузерные при включённых настройках. См. [TOOLS.md](../TOOLS.md).

Переключатель **Custom tools** отключает группу: `rag_search`, `plan_tool`, `reasoning_tool`, `code_interpreter`, `library_context`, `file_versions_tool`, `project_brain_tool` (`_CUSTOM_TOOL_NAMES` в `Agent/tool_registry.py`).
