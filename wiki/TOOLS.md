# Справочник инструментов TCA

Здесь приведен список основных инструментов агента. Для каждого инструмента доступна **детальная документация с разбором кода** в папке [tool/](tool/).

## Сводная таблица

| Категория | Инструмент | Описание | Подробнее |
|-----------|------------|----------|-----------|
| **Файлы** | `read_file` | Чтение (с постраничностью) | [file_ops.md](tool/file_ops.md) |
| | `edit_file` | Умная замена текста | [file_ops.md](tool/file_ops.md) |
| | `write_file` | Полная перезапись | [file_ops.md](tool/file_ops.md) |
| | `list_files` | Список файлов | [file_ops.md](tool/file_ops.md) |
| | `create_code` | Создание файлов кода | [code_gen.md](tool/code_gen.md) |
| **Система** | `run_command` | Запуск в терминале | [terminal_tool.md](tool/terminal_tool.md) |
| | `python` | Code Interpreter | [code_interpreter.md](tool/code_interpreter.md) |
| **Git** | `git_status` | Состояние репозитория | [git_tool.md](tool/git_tool.md) |
| | `git_log` | История изменений | [git_tool.md](tool/git_tool.md) |
| **Планирование**| `save_plan` | Создание чек-листа | [planning_tool.md](tool/planning_tool.md) |
| | `update_plan` | Отметка прогресса | [planning_tool.md](tool/planning_tool.md) |
| **Веб** | `web_search` | Поиск в интернете | [web_tool.md](tool/web_tool.md) |
| | `browser_*` | Автоматизация (Playwright) | [browser_tool.md](tool/browser_tool.md) |
| | `docs` | Библиотечная справка | [context7_tool.md](tool/context7_tool.md) |
| **Мышление** | `think` | Логирование рассуждений | [thinking_tool.md](tool/thinking_tool.md) |
| | `ask_user` | Вопрос пользователю | [interactive.md](tool/interactive.md) |
| **Безопасность**| `rollback` | Откат версий файла | [versioning_tool.md](tool/versioning_tool.md) |
| **Разное** | `create_pdf` | Генерирация документов | [pdf_tool.md](tool/pdf_tool.md) |
| | `custom` | Ваши инструменты | [custom_tools.md](tool/custom_tools.md) |

---

## Описание базовых функций

### Файловые операции
Агент использует `file_ops.py` для большинства задач. Если файл слишком большой, он читает его по частям (`offset`/`limit`), чтобы не превысить лимит памяти (контекста).

### Терминал и безопасность
Команда `run_command` всегда запрашивает ваше подтверждение в интерфейсе, прежде чем выполнить что-то потенциально опасное (удаление, установка пакетов).

### Версионирование
Перед каждой правкой через `edit_file` система делает "снимок" в локальную базу данных. Если агент ошибся, он может вызвать `rollback_file`, чтобы всё вернуть как было.

### Веб-инструменты
Агент может искать информацию двумя способами:
1. Быстрый поиск в DuckDuckGo (`web_search`).
2. Глубокое исследование сайта через полноценный браузер (`browser_open_url`), если нужно нажать кнопку или прокрутить страницу.
