"""Инструменты отката/версий файлов для агента."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from langchain_core.tools import tool

try:
    from ..path_utils import resolve_abs_path
    from ..versioning import list_versions as _list_versions
    from ..versioning import rollback_to_version as _rollback_to_version
    from ..versioning import rollback_last as _rollback_last
except ImportError:
    from Agent.path_utils import resolve_abs_path
    from Agent.versioning import list_versions as _list_versions
    from Agent.versioning import rollback_to_version as _rollback_to_version
    from Agent.versioning import rollback_last as _rollback_last


@tool
def list_file_versions(path: str, limit: int = 20) -> Dict[str, Any]:
    """Показывает последние сохранённые версии файла для отката."""
    p = resolve_abs_path(path)
    return {"path": str(p), "versions": _list_versions(str(p), limit=limit)}


@tool
def rollback_file(path: str, version_id: str = "") -> Dict[str, Any]:
    """Откатывает файл. Если version_id пустой — откат к последней сохранённой версии."""
    p = resolve_abs_path(path)
    if version_id.strip():
        return _rollback_to_version(str(p), version_id.strip())
    return _rollback_last(str(p))

