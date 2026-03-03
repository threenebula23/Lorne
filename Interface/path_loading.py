from pathlib import Path
from typing import Optional


def resolve_path(path_str: str) -> Path:
    """Разрешает путь (относительный/абсолютный, ~) в абсолютный Path."""
    p = Path(path_str).expanduser()
    return (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()


def select_directory(initial: Optional[str] = None) -> Optional[Path]:
    """Заглушка: в будущем — диалог выбора директории. Пока возвращает initial или cwd."""
    if initial:
        return resolve_path(initial)
    return Path.cwd()
