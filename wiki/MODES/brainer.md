# Режим: brainer

## Реализация

- Ключ `_MODE_ADDONS["brainer"]` в `Agent/prompts/__init__.py` — акцент на `rag_search` и каталог `project_brain/**`, затем исходники.
- Набор тулов как у обычного режима чата, в котором выбран Brainer (нет отдельного `brainer` флага в `build_tools`; отличие — системный текст и дисциплина использования).

## Схема потока

```mermaid
flowchart LR
  user[User] --> rag[rag_search_brain_first]
  rag --> read[read_file_project_brain]
  read --> code[Source_files]
```

## Инструменты

`project_brain_tool` (refresh / write_brain / write_architecture / …), `rag_search`, чтение файлов — в приоритете. См. [PROJECT_BRAIN.md](../PROJECT_BRAIN.md).

## Автообновление brain

В коде графа: после каждого раунда с тулами выполняется переиндексация RAG с диска; после финального ответа без тулов — полный `refresh_project_brain` (скан) + переиндексация. При остановке пользователем (TUI / classic) — тот же полный refresh, если режим Brainer.
