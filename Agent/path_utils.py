"""Общая утилита разрешения путей для агента и модуля загрузки Path."""
from pathlib import Path


def resolve_abs_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path
