# Режим: research

## Реализация

- Ключ `_MODE_ADDONS["research"]`; в TUI `research` → `agent_mode=True` для расширенного набора (браузер по prefs).
- Доп. параметры: `research_max_sources`, `research_max_rounds`, `research_deep_fetch` в `Interface/ui_prefs.py` / `ui_settings.json`.

## Схема потока

```mermaid
flowchart LR
  user[User] --> chat[Chat]
  chat --> graph[Graph]
  graph --> web[web_search_web_fetch]
  graph --> lib[library_context]
  graph --> rag[rag_search]
```

## Инструменты

Как у Agent (после `_sync_tui_tool_bundle("research")`), с акцентом на веб и документацию в системном фрагменте режима. После каждого раунда с тулами RAG brain переиндексируется с диска (как в Brainer), чтобы ``rag_search`` подхватывал свежие ``project_brain/*.md`` без ожидания конца хода.
