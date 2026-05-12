# Настройки UI (`ui_settings.json`)

Файл создаётся в каталоге данных проекта: **`project_data_dir`** (`.lorne` или существующий `.tca`) — см. `Agent/runtime_paths.py`. Имя файла: **`ui_settings.json`**.

Загрузка/сохранение: **`Interface/ui_prefs.py`** (`load_prefs`, `save_prefs`, `prefs_path`). Неизвестные ключи из JSON отбрасываются; отсутствующие дополняются из `DEFAULT_PREFS`.

## Ключи `DEFAULT_PREFS`

| Ключ | Тип / значение по умолчанию | Назначение |
|------|------------------------------|------------|
| `theme` | str, `"Purple Dark"` | Тема TUI (Textual) |
| `cli_theme` | str, `"purple"` | Пресет classic CLI (`Interface/cli_theme.py`) |
| `cli_accent_color` | str, hex | Акцент classic CLI |
| `density` | `"normal"` | Плотность UI: `normal` \| `compact` \| `spacious` |
| `syntax_theme` | `"monokai"` | Подсветка в редакторе |
| `accent_color` | hex | Акцент TUI |
| `playwright_python_enabled` | bool `false` | Python Playwright в режиме Agent |
| `browser_tools_enabled` | bool `true` | Node headless browser в Agent |
| `custom_tools_enabled` | bool `true` | RAG, plan, reasoning, interpreter, library, versions, brain |
| `openrouter_custom_models` | list | Пользовательские модели OpenRouter |
| `ollama_custom_models` | list | Пользовательские модели Ollama |
| `ollama_base_url` | URL | База Ollama API |
| `ollama_api_key` | str | Ключ при необходимости |
| `ollama_presets` | dict | Пресеты параметров Ollama |
| `ollama_model_settings` | dict | Пер-модельные настройки |
| `orchestration_mode` | `"auto"` | Creator: `parallel` \| `pipeline` \| `auto` |
| `orchestration_max_workers` | int `4` | Параллельные воркеры Creator |
| `research_max_sources` | int | Лимит источников Research |
| `research_max_rounds` | int | Раунды Research |
| `research_deep_fetch` | bool | Глубокий fetch в Research |
| `cli_prompt_glyph` | str | Префикс строки ввода classic |

## Как менять

1. **UI** — вкладки в `FileExplorerPanel` (персонализация, агенты, OpenRouter, Ollama).
2. **Вручную** — отредактировать `ui_settings.json` в каталоге данных проекта; перезапуск или перечитывание prefs по месту использования.

## Влияние на туловый набор

`Agent/agent/_impl_prepare.py` — **`_sync_tui_tool_bundle(mode)`** читает prefs и вызывает `set_tool_session_prefs` + `build_tools` с флагами `ask_mode`, `agent_mode`, `playwright_python`, `browser_tools`, `custom_tools`.

Связка режимов TUI и тулов: [../MODES/README.md](../MODES/README.md).
