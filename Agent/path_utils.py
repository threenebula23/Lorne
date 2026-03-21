"""Общая утилита разрешения путей для агента и модуля загрузки Path."""
from pathlib import Path
from typing import Optional

_GLOBAL_PROJECT_ROOT: Optional[Path] = None

def set_project_root(root: Path | str) -> None:
    global _GLOBAL_PROJECT_ROOT
    _GLOBAL_PROJECT_ROOT = Path(root).expanduser().resolve()

def resolve_abs_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if path.is_absolute():
        return path.resolve()
    
    global _GLOBAL_PROJECT_ROOT
    base_dir = _GLOBAL_PROJECT_ROOT if _GLOBAL_PROJECT_ROOT is not None else Path.cwd()
    return (base_dir / path).resolve()

