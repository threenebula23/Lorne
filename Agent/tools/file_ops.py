"""Инструменты работы с файлами: чтение, листинг, поиск в подпапках, редактирование."""
import os
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.tools import tool

try:
    from ..path_utils import resolve_abs_path
    from ..versioning import save_version
except ImportError:
    def resolve_abs_path(path_str: str) -> Path:
        p = Path(path_str).expanduser()
        return (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()
    def save_version(path: str, content: str, note: str = "") -> str:
        return ""


def _git_auto_snapshot(file_path: str, action: str) -> None:
    """Attempt a Git auto-snapshot after file modification."""
    try:
        from Agent.git_integration import get_git_manager
        gm = get_git_manager()
        if gm.available:
            rel = os.path.relpath(file_path, os.getcwd())
            gm.auto_snapshot(f"{action}: {rel}", files=[file_path])
    except Exception:
        pass


def _skip_dir(name: str) -> bool:
    return name.startswith(".") or name == "__pycache__" or name == "node_modules" or name == ".git"


@tool
def read_file(filename: str, encoding: str = "utf-8",
              offset: int = 0, limit: int = 0) -> Dict[str, Any]:
    """Читает содержимое файла. filename — путь к файлу. offset — начальная строка (0-based), limit — кол-во строк (0 = весь файл). Для больших файлов используй offset+limit для чтения по частям."""
    full_path = resolve_abs_path(filename)
    try:
        content = full_path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        content = "(бинарный или не UTF-8 файл)"
    all_lines = content.splitlines(keepends=True)
    total_lines = len(all_lines)

    if offset > 0 or limit > 0:
        start = max(0, offset)
        end = start + limit if limit > 0 else total_lines
        selected = all_lines[start:end]
        content = "".join(selected)
        return {
            "file_path": str(full_path),
            "content": content,
            "total_lines": total_lines,
            "offset": start,
            "limit": len(selected),
            "showing": f"строки {start + 1}-{start + len(selected)} из {total_lines}",
        }

    return {"file_path": str(full_path), "content": content, "total_lines": total_lines}


@tool
def list_files(path: str, recursive: bool = False, pattern: str = "*") -> Dict[str, Any]:
    """Список файлов в директории. path — путь к папке; recursive=True — обход подпапок; pattern — glob, например *.py."""
    full_path = resolve_abs_path(path)
    all_entries: List[Dict[str, Any]] = []
    if not recursive:
        for item in sorted(full_path.iterdir(), key=lambda x: x.name.lower()):
            if _skip_dir(item.name):
                continue
            all_entries.append({
                "path": str(item),
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
            })
        return {"path": str(full_path), "entries": all_entries, "recursive": False}
    for p in full_path.rglob(pattern):
        if not p.is_file():
            continue
        rel = p.relative_to(full_path)
        if any(_skip_dir(part) for part in rel.parts):
            continue
        all_entries.append({"path": str(p), "relative": str(rel), "name": p.name})
    return {"path": str(full_path), "entries": all_entries[:500], "recursive": True}


@tool
def search_in_files(directory: str, query: str, file_pattern: str = "*.py", max_files: int = 50) -> Dict[str, Any]:
    """Поиск текста в файлах в директории и подпапках. directory — корень поиска, query — строка для поиска, file_pattern — glob (например *.py)."""
    root = resolve_abs_path(directory)
    results: List[Dict[str, Any]] = []
    query_lower = query.lower()
    n = 0
    for f in root.rglob(file_pattern):
        if not f.is_file() or n >= max_files:
            break
        if any(_skip_dir(part) for part in f.relative_to(root).parts):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            if query_lower in text.lower():
                lines = [i + 1 for i, line in enumerate(text.splitlines()) if query_lower in line.lower()]
                results.append({"file": str(f), "lines": lines[:20]})
                n += 1
        except Exception:
            continue
    return {"query": query, "directory": str(root), "matches": results}


@tool
def edit_file(path: str, old_str: str, new_str: str) -> Dict[str, Any]:
    """Заменяет первое вхождение old_str на new_str. Если old_str пустой — создаёт/перезаписывает файл содержимым new_str. Возвращает total_lines — всего строк в файле после записи."""
    full_path = resolve_abs_path(path)
    if old_str == "":
        before_text = ""
        before_total_lines = 0
        snapshot_id = ""
        full_path.parent.mkdir(parents=True, exist_ok=True)
        if full_path.exists():
            before_text = full_path.read_text(encoding="utf-8", errors="ignore")
            before_total_lines = len(before_text.splitlines())
            snapshot_id = save_version(str(full_path), before_text, note="before-edit_file-create") or ""
        full_path.write_text(new_str, encoding="utf-8")
        lines = len(new_str.splitlines())
        after_total_lines = lines
        return {
            "path": str(full_path),
            "action": "created_file",
            "lines": lines,
            "before_total_lines": before_total_lines,
            "after_total_lines": after_total_lines,
            "delta_total_lines": after_total_lines - before_total_lines,
            "total_lines": after_total_lines,
            "snapshot_id": snapshot_id,
        }
    try:
        original = full_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"path": str(full_path), "action": "file_not_found"}
    before_total_lines = len(original.splitlines())
    if old_str not in original:
        return {"path": str(full_path), "action": "old_str not found"}
    snapshot_id = save_version(str(full_path), original, note="before-edit_file-replace") or ""
    edited = original.replace(old_str, new_str, 1)
    full_path.write_text(edited, encoding="utf-8")
    _git_auto_snapshot(str(full_path), "edit_file")
    old_lines = len(old_str.splitlines())
    new_lines = len(new_str.splitlines())
    total_lines = len(edited.splitlines())
    return {
        "path": str(full_path),
        "action": "edited",
        "lines_before": old_lines,
        "lines_after": new_lines,
        "lines_delta": new_lines - old_lines,
        "total_lines": total_lines,
        "before_total_lines": before_total_lines,
        "after_total_lines": total_lines,
        "delta_total_lines": total_lines - before_total_lines,
        "snapshot_id": snapshot_id,
    }


@tool
def write_file(path: str, content: str) -> Dict[str, Any]:
    """Создаёт или полностью перезаписывает файл содержимым. Удобно для создания нового кода. Возвращает path, total_lines."""
    full_path = resolve_abs_path(path)
    before_text = ""
    before_total_lines = 0
    snapshot_id = ""
    full_path.parent.mkdir(parents=True, exist_ok=True)
    if full_path.exists():
        before_text = full_path.read_text(encoding="utf-8", errors="ignore")
        before_total_lines = len(before_text.splitlines())
        snapshot_id = save_version(str(full_path), before_text, note="before-write_file") or ""
    full_path.write_text(content, encoding="utf-8")
    total_lines = len(content.splitlines())
    _git_auto_snapshot(str(full_path), "write_file")
    return {
        "path": str(full_path),
        "action": "written",
        "total_lines": total_lines,
        "before_total_lines": before_total_lines,
        "after_total_lines": total_lines,
        "delta_total_lines": total_lines - before_total_lines,
        "snapshot_id": snapshot_id,
    }


@tool
def get_file_line_count(path: str) -> Dict[str, Any]:
    """Возвращает количество строк в файле. Полезно для отображения состояния файла."""
    full_path = resolve_abs_path(path)
    text = full_path.read_text(encoding="utf-8", errors="ignore")
    total_lines = len(text.splitlines())
    return {"path": str(full_path), "total_lines": total_lines}
