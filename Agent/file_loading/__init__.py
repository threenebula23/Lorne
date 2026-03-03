from pathlib import Path
from typing import List, Optional

try:
    from ..path_utils import resolve_abs_path
except ImportError:
    def resolve_abs_path(path_str: str) -> Path:
        p = Path(path_str).expanduser()
        return (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()


def load_file(path: str, encoding: str = "utf-8") -> str:
    """Загружает содержимое файла как текст."""
    return resolve_abs_path(path).read_text(encoding=encoding)


def load_directory_texts(path: str, pattern: str = "*", max_size: int = 1024 * 1024) -> List[tuple]:
    """Загружает текстовое содержимое файлов в директории (и подпапках). Возвращает [(путь, текст), ...]."""
    root = resolve_abs_path(path)
    out: List[tuple] = []
    total = 0
    for f in root.rglob(pattern):
        if not f.is_file() or "__pycache__" in str(f) or f.suffix in (".pyc",):
            continue
        if total >= max_size:
            break
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            total += len(text)
            out.append((str(f), text))
        except Exception:
            continue
    return out
