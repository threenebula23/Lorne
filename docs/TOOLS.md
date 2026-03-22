# Справочник инструментов TCA

Описание инструментов, доступных агенту. **Точное число** зависит от сборки: базовый набор в `Agent/tool_registry.py`, опционально Git / Context7 / браузер, пользовательские инструменты (`/custom`), в режиме агента — инструменты Playwright. Подробнее: [ARCHITECTURE.md](./ARCHITECTURE.md), раздел `tool_registry`.

## Файлы

### `read_file(filename, encoding, offset, limit)`
Чтение файла с постраничностью для больших файлов.
- `filename` — путь
- `encoding` (по умолчанию `utf-8`)
- `offset` — с какой строки (с нуля)
- `limit` — сколько строк (0 = весь файл)

### `list_files(path, recursive, pattern)`
Список файлов в каталоге.

### `search_in_files(directory, query, file_pattern, max_files)`
Полнотекстовый поиск по файлам.

### `edit_file(path, old_str, new_str)`
Замена первого вхождения `old_str` на `new_str`. Пустой `old_str` — создание/перезапись. Перед правкой создаётся снимок версии.

### `write_file(path, content)`
Полная перезапись файла, создание родительских каталогов, снимок и при необходимости git.

### `create_code_file(filepath, language, code)`
Создание файла с расширением по языку.

### `append_code_snippet(filepath, snippet, language)`
Добавление кода в конец файла.

### `get_file_line_count(path)`
Число строк в файле.

## Терминал

### `run_command(command, cwd, timeout_seconds)`
Shell-команда с подтверждением пользователя.
- `cwd` — рабочая директория (пусто = корень проекта)
- `timeout_seconds` — таймаут (по умолчанию 30)

Защита: блокировка опасных команд (`rm -rf` и т.д.), дедупликация частых повторов.

### `code_interpreter(code, timeout)`
Запуск Python в отдельном процессе.

## Планирование

### `save_plan(title, steps)`
Сохранение плана (шаги — список строк).

### `load_plan()`
Загрузка плана из `.tca_plan.json`.

### `update_plan(step_index, status, note)`
Обновление шага: `pending` | `in_progress` | `completed` | `blocked`.

### `clear_plan()`
Удаление текущего плана.

## Git

### `git_log(path, limit)`
История коммитов; `path` пустой — по всему репозиторию.

### `git_diff(commit)`
Diff коммита или текущих незакоммиченных изменений.

### `git_rollback_file(path, commit)`
Восстановление файла из коммита.

### `git_status()`
Ветка, изменённые / staged / неотслеживаемые файлы.

## Версионирование (SQLite)

### `list_file_versions(path, limit)`
Список снимков файла (новые первыми).

### `rollback_file(path, version_id)`
Откат к снимку или к последнему.

## Веб и документация

### `web_search(query, max_results)`
Поиск через DuckDuckGo.

### `web_fetch(url, max_length)`
Загрузка страницы как текста.

### `get_documentation(query, library)`
Поиск по документации библиотек и API.

## RAG

### `rag_search(query, top_k)`
Поиск по индексу проекта: чанки ~800 символов с перекрытием, учёт границ функций/классов в Python, word-level scoring, в ответе путь, строки, оценка.

## Прочее

### `ask_user(question)`
Вопрос пользователю в терминале (classic).

### `create_pdf(filepath, title, body)`
Создание PDF (при отсутствии ReportLab — fallback в `.txt`).
