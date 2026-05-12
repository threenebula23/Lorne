"""Per-mode system fragments appended when the user switches TUI mode."""

from __future__ import annotations

from typing import Dict

_JSON_IN_TOOLS = (
    "Строковые JSON-аргументы (`steps_json`, `data_json`, …): одна строка = **полный** "
    "валидный JSON в **двойных** кавычках, без обрыва; для `plan_tool` save надёжнее "
    "поле `steps` как массив строк."
)

_MODE_ADDONS: Dict[str, str] = {
    "agent": (
        "### Режим Agent\n"
        "Полный цикл с тулами. Дисциплина: `list_files`/`search_in_files` → `read_file` → "
        "`rag_search` для архитектуры → `plan_tool` на многошаговые задачи → правки "
        "(`replace_file_lines`/`insert_file_lines`/`write_file`/`code_file_tool`) → "
        "`run_command`/`run_package_script`. Перед длинной цепочкой — `reasoning_tool` think.\n"
        + _JSON_IN_TOOLS
    ),
    "ask": (
        "### Режим Ask\n"
        "Доступны только чтение и поиск: `list_files`, `read_file`, `read_file_lines`, "
        "`search_in_files`, `find_in_file`, `rag_search`, `web_search`, `web_fetch`, "
        "`library_context`, `get_file_line_count`, `ask_user`, `reasoning_tool` (think/analyze), "
        "`ocr_tool`, `office_document_read` — **без** записи в файлы, без `run_command`, "
        "`edit_file`, `write_file`, `code_interpreter`, `project_brain_tool`.\n"
        + _JSON_IN_TOOLS
    ),
    "creator": (
        "### Режим Creator\n"
        "Параллельные воркеры: формулируй цель и критерии готовности; веди `plan_tool`; "
        "каждый воркер — отдельные чтения/правки по схемам, без дублирования одних и тех же путей.\n"
        + _JSON_IN_TOOLS
    ),
    "research": (
        "### Режим Research\n"
        "Опора на внешние источники: `web_search` → `web_fetch` для деталей; `library_context` "
        "для версий API пакетов; при связи с кодом репозитория — `rag_search` и `read_file`.\n"
        + _JSON_IN_TOOLS
    ),
    "deep": (
        "### Режим Deep\n"
        "Длинный автономный цикл: часто `plan_tool` + `reasoning_tool`; фиксируй факты из "
        "`read_file`/`rag_search`; избегай повторов; чекпоинты — по UI; завершай отчётом.\n"
        + _JSON_IN_TOOLS
    ),
    "brainer": (
        "### Режим Brainer\n"
        "Сначала `rag_search` и файлы `project_brain/**`, затем исходники; при устаревшем brain "
        "— `project_brain_tool` refresh, снова `rag_search`.\n"
        + _JSON_IN_TOOLS
    ),
}


def mode_prompt_addon(mode: str) -> str:
    """Return a short system fragment for ``mode`` slug, or empty string."""
    key = (mode or "").strip().lower()
    return _MODE_ADDONS.get(key, "")
