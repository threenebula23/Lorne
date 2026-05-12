"""Git tools for the Lorne agent — log, diff, rollback via LangChain @tool."""
from typing import Any, Dict

from langchain_core.tools import tool


def _get_gm():
    from Agent.git_integration import get_git_manager
    return get_git_manager()


@tool
def git_log(path: str = "", limit: int = 15) -> Dict[str, Any]:
    """Показать историю Git-коммитов. path — фильтр по файлу (пусто = весь проект), limit — макс. число коммитов."""
    gm = _get_gm()
    if not gm.available:
        return {"error": "Git не инициализирован в этом проекте"}
    commits = gm.log(path=path or None, limit=limit)
    return {"commits": commits, "count": len(commits), "branch": gm.current_branch()}


@tool
def git_diff(commit: str = "") -> Dict[str, Any]:
    """Показать diff. commit — хеш коммита (пусто = текущие изменения)."""
    gm = _get_gm()
    if not gm.available:
        return {"error": "Git не инициализирован в этом проекте"}
    diff_text = gm.diff(commit_hash=commit or None)
    return {"diff": diff_text[:5000], "truncated": len(diff_text) > 5000}


@tool
def git_rollback_file(path: str, commit: str = "") -> Dict[str, Any]:
    """Откатить файл к указанному коммиту. path — путь к файлу, commit — хеш (пусто = последний коммит)."""
    gm = _get_gm()
    return gm.rollback_file(path=path, commit_hash=commit or None)


@tool
def git_status() -> Dict[str, Any]:
    """Показать текущий статус Git-репозитория: ветка, изменения, staged файлы."""
    gm = _get_gm()
    return gm.status_summary()
