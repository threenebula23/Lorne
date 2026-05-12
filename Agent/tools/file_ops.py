"""Инструменты работы с файлами: чтение, листинг, поиск в подпапках, редактирование."""
import fnmatch
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _content_to_line_chunks(content: str) -> List[str]:
    """Разбивает вставляемый текст на физические строки с сохранением переводов (как в splitlines(keepends=True))."""
    if content == "":
        return []
    # Несколько логических строк без финального \\n — иначе последняя склеится со следующей строкой файла.
    if "\n" in content and not content.endswith("\n"):
        content = content + "\n"
    if content.endswith("\n"):
        return content.splitlines(keepends=True)
    parts = content.split("\n")
    out: List[str] = []
    for i, p in enumerate(parts):
        if i < len(parts) - 1:
            out.append(p + "\n")
        else:
            out.append(p)
    return out


def _old_str_variants(old_str: str) -> List[str]:
    """Варианты old_str для поиска: точный, LF↔CRLF (модель часто шлёт \\n, файл с Windows — \\r\\n)."""
    out: List[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    add(old_str)
    if "\r\n" in old_str:
        add(old_str.replace("\r\n", "\n"))
    elif "\n" in old_str:
        add(old_str.replace("\n", "\r\n"))
    return out


def _new_str_for_variant(old_variant: str, old_original: str, new_str: str) -> str:
    """Подгоняет переводы строк в new_str к тому варианту old_str, который сматчился."""
    if old_variant == old_original:
        return new_str
    if "\r\n" not in old_original and old_variant == old_original.replace("\n", "\r\n"):
        return new_str.replace("\n", "\r\n")
    if "\r\n" in old_original and old_variant == old_original.replace("\r\n", "\n"):
        return new_str.replace("\r\n", "\n")
    return new_str


def _replace_first_occurrence(text: str, old_str: str, new_str: str) -> Optional[str]:
    """Одна замена old_str → new_str; учитывает рассогласование \\n vs \\r\\n между моделью и файлом."""
    for old_variant in _old_str_variants(old_str):
        if old_variant not in text:
            continue
        new_out = _new_str_for_variant(old_variant, old_str, new_str)
        return text.replace(old_variant, new_out, 1)
    return None


# Auto-truncate threshold (in lines) for ``read_file`` when called without
# an explicit range. Prevents the model from accidentally pulling a 5k-line
# file into context. The model can still request the rest via offset/limit
# or via ``read_file_lines``.
_READ_FILE_AUTO_HEAD_LINES = 400
_READ_FILE_HARD_LINE_CAP = 5000


@tool
def read_file(filename: str, encoding: str = "utf-8",
              offset: int = 0, limit: int = 0) -> Dict[str, Any]:
    """Чтение файла: offset/limit (0-based строки); без диапазона длинные файлы обрезаются (~400 строк) — дальше read_file_lines."""
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
        end = min(end, start + _READ_FILE_HARD_LINE_CAP)
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

    if total_lines > _READ_FILE_AUTO_HEAD_LINES:
        head = all_lines[:_READ_FILE_AUTO_HEAD_LINES]
        return {
            "file_path": str(full_path),
            "content": "".join(head),
            "total_lines": total_lines,
            "offset": 0,
            "limit": _READ_FILE_AUTO_HEAD_LINES,
            "showing": (
                f"строки 1-{_READ_FILE_AUTO_HEAD_LINES} из {total_lines} "
                f"(авто-обрезка; используйте read_file_lines для нужного диапазона)"
            ),
            "truncated": True,
        }

    return {"file_path": str(full_path), "content": content, "total_lines": total_lines}


@tool
def read_file_lines(filename: str, start_line: int = 1, end_line: int = 0,
                    encoding: str = "utf-8") -> Dict[str, Any]:
    """Фрагмент по строкам (1-based start_line..end_line; end_line=0 — до конца, кап 5000 строк). Номера в content как ``N|``."""
    full_path = resolve_abs_path(filename)
    try:
        raw = full_path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return {
            "file_path": str(full_path),
            "error": "binary_or_non_utf8",
            "content": "",
            "total_lines": 0,
        }
    except FileNotFoundError:
        return {
            "file_path": str(full_path),
            "error": "file_not_found",
            "content": "",
            "total_lines": 0,
        }

    lines = raw.splitlines()
    total = len(lines)
    start = max(1, int(start_line or 1))
    if start > total:
        return {
            "file_path": str(full_path),
            "content": "",
            "total_lines": total,
            "start_line": start,
            "end_line": start - 1,
            "showing": f"пустой диапазон: файл содержит {total} строк",
        }
    if end_line and int(end_line) > 0:
        end = min(total, int(end_line))
    else:
        end = total
    end = min(end, start + _READ_FILE_HARD_LINE_CAP - 1)
    if end < start:
        end = start

    pad = len(str(end))
    body = "\n".join(f"{n:>{pad}}| {lines[n - 1]}" for n in range(start, end + 1))

    return {
        "file_path": str(full_path),
        "content": body,
        "total_lines": total,
        "start_line": start,
        "end_line": end,
        "showing": f"строки {start}-{end} из {total}",
    }


@tool
def list_files(path: str = ".", recursive: bool = False, pattern: str = "*") -> Dict[str, Any]:
    """Список файлов в каталоге. path — папка (\"\" или \".\" = текущая). recursive — рекурсивно. pattern — glob по **имени** файла (например *.py)."""
    raw = (path or "").strip() or "."
    full_path = resolve_abs_path(raw)
    pat = (pattern or "*").strip() or "*"
    if not full_path.exists():
        return {
            "path": str(full_path), "error": "not_found", "entries": [],
            "recursive": bool(recursive), "pattern": pat,
        }
    if full_path.is_file():
        return {
            "path": str(full_path),
            "entries": [{"path": str(full_path), "name": full_path.name, "type": "file"}],
            "recursive": False,
            "note": "path_is_file",
            "pattern": pat,
        }
    if not full_path.is_dir():
        return {
            "path": str(full_path), "error": "not_a_directory", "entries": [],
            "recursive": bool(recursive), "pattern": pat,
        }

    all_entries: List[Dict[str, Any]] = []
    if not recursive:
        try:
            for item in sorted(full_path.iterdir(), key=lambda x: x.name.lower()):
                if _skip_dir(item.name):
                    continue
                if not fnmatch.fnmatch(item.name, pat):
                    continue
                all_entries.append({
                    "path": str(item),
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                })
        except OSError as e:
            return {
                "path": str(full_path), "error": str(e), "entries": [],
                "recursive": False, "pattern": pat,
            }
        return {
            "path": str(full_path), "entries": all_entries, "recursive": False, "pattern": pat,
        }

    try:
        for p in full_path.rglob("*"):
            if not p.is_file():
                continue
            if not fnmatch.fnmatch(p.name, pat):
                continue
            rel = p.relative_to(full_path)
            if any(_skip_dir(part) for part in rel.parts):
                continue
            all_entries.append({"path": str(p), "relative": str(rel), "name": p.name})
    except OSError as e:
        return {
            "path": str(full_path), "error": str(e), "entries": [],
            "recursive": True, "pattern": pat,
        }
    return {
        "path": str(full_path), "entries": all_entries[:500], "recursive": True, "pattern": pat,
    }


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
def find_in_file(
    file_path: str,
    pattern: str,
    regex: bool = False,
    case_insensitive: bool = True,
    max_matches: int = 100,
    context_lines: int = 0,
) -> Dict[str, Any]:
    """Один файл: подстрока или regex + номера строк; большие файлы — сначала read_file_lines."""
    p = resolve_abs_path(file_path)
    if not p.is_file():
        return {"file_path": str(p), "error": "not_found_or_not_file", "matches": []}
    if not (pattern or "").strip():
        return {"file_path": str(p), "error": "empty_pattern", "matches": []}
    if context_lines > 20:
        context_lines = 20
    if context_lines < 0:
        context_lines = 0
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"file_path": str(p), "error": str(e), "matches": []}

    lines = text.splitlines()
    out: List[Dict[str, Any]] = []
    n = 0
    flags = re.IGNORECASE if case_insensitive and regex else 0
    if regex:
        try:
            cre = re.compile((pattern or "").strip(), flags)
        except re.error as e:
            return {
                "file_path": str(p),
                "error": f"invalid_regex: {e}",
                "matches": [],
            }

        for i, line in enumerate(lines, start=1):
            if n >= max_matches:
                break
            if cre.search(line):
                rec: Dict[str, Any] = {"line": i, "text": line}
                if context_lines and context_lines > 0:
                    lo = max(0, i - 1 - context_lines)
                    hi = min(len(lines), i + context_lines)
                    rec["context"] = "\n".join(
                        f"{j + 1:6d}|{lines[j]}" for j in range(lo, hi)
                    )
                out.append(rec)
                n += 1
    else:
        needle = (pattern or "").lower() if case_insensitive else (pattern or "")
        for i, line in enumerate(lines, start=1):
            if n >= max_matches:
                break
            hay = line.lower() if case_insensitive else line
            if (needle in hay) if case_insensitive else ((pattern or "") in line):
                rec = {"line": i, "text": line}
                if context_lines and context_lines > 0:
                    lo = max(0, i - 1 - context_lines)
                    hi = min(len(lines), i + context_lines)
                    rec["context"] = "\n".join(
                        f"{j + 1:6d}|{lines[j]}" for j in range(lo, hi)
                    )
                out.append(rec)
                n += 1

    return {
        "file_path": str(p),
        "pattern": pattern,
        "regex": bool(regex),
        "case_insensitive": bool(case_insensitive),
        "match_count": len(out),
        "matches": out,
        "truncated": len(out) >= max_matches,
    }


@tool
def edit_file(path: str, old_str: str, new_str: str) -> Dict[str, Any]:
    """Заменяет первое вхождение old_str на new_str. Пустой old_str — перезапись файла содержимым new_str."""
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
        original = full_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return {"path": str(full_path), "action": "file_not_found"}
    before_total_lines = len(original.splitlines())
    edited = _replace_first_occurrence(original, old_str, new_str)
    if edited is None:
        return {"path": str(full_path), "action": "old_str not found"}
    snapshot_id = save_version(str(full_path), original, note="before-edit_file-replace") or ""
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
    """Создать или перезаписать файл содержимым (content)."""
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
def replace_file_lines(path: str, start_line: int, end_line: int, content: str) -> Dict[str, Any]:
    """Заменить строки start_line..end_line (1-based, включительно) на content. Пустой content — удаление диапазона."""
    full_path = resolve_abs_path(path)
    if start_line < 1 or end_line < start_line:
        return {"path": str(full_path), "error": "invalid_line_range", "start_line": start_line, "end_line": end_line}
    try:
        raw = full_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"path": str(full_path), "error": "file_not_found"}
    lines = raw.splitlines(keepends=True)
    n = len(lines)
    if n == 0:
        if start_line != 1 or end_line < 1:
            return {"path": str(full_path), "error": "empty_file_use_start_1_end_1", "total_lines": 0}
        end_line = 0
    else:
        if start_line > n:
            return {"path": str(full_path), "error": "start_line past eof", "total_lines": n}
        end_line = min(end_line, n)
    before_total = n
    snapshot_id = save_version(str(full_path), raw, note="before-replace_file_lines") or ""
    new_block = _content_to_line_chunks(content)
    new_lines = lines[: start_line - 1] + new_block + lines[end_line:]
    new_text = "".join(new_lines)
    full_path.write_text(new_text, encoding="utf-8")
    _git_auto_snapshot(str(full_path), "replace_file_lines")
    after_total = len(new_text.splitlines())
    removed = end_line - start_line + 1
    added = len(new_block)
    return {
        "path": str(full_path),
        "action": "lines_replaced",
        "start_line": start_line,
        "end_line": end_line,
        "removed_lines": removed,
        "inserted_lines": added,
        "before_total_lines": before_total,
        "after_total_lines": after_total,
        "delta_total_lines": after_total - before_total,
        "total_lines": after_total,
        "snapshot_id": snapshot_id,
    }


@tool
def insert_file_lines(path: str, after_line: int, content: str) -> Dict[str, Any]:
    """Вставить content после строки after_line (0 = в начало; k = после k-й строки, 1-based)."""
    full_path = resolve_abs_path(path)
    if after_line < 0:
        return {"path": str(full_path), "error": "after_line must be >= 0"}
    if not content:
        return {"path": str(full_path), "error": "empty_content"}
    try:
        raw = full_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        raw = ""
    lines = raw.splitlines(keepends=True)
    n = len(lines)
    if after_line > n:
        return {"path": str(full_path), "error": "after_line past eof", "total_lines": n}
    before_total = n
    snapshot_id = save_version(str(full_path), raw, note="before-insert_file_lines") or ""
    block = _content_to_line_chunks(content)
    insert_at = after_line
    new_lines = lines[:insert_at] + block + lines[insert_at:]
    new_text = "".join(new_lines)
    full_path.write_text(new_text, encoding="utf-8")
    _git_auto_snapshot(str(full_path), "insert_file_lines")
    after_total = len(new_text.splitlines())
    added = len(block)
    return {
        "path": str(full_path),
        "action": "lines_inserted",
        "after_line": after_line,
        "inserted_lines": added,
        "before_total_lines": before_total,
        "after_total_lines": after_total,
        "delta_total_lines": after_total - before_total,
        "total_lines": after_total,
        "snapshot_id": snapshot_id,
    }


@tool
def get_file_line_count(path: str) -> Dict[str, Any]:
    """Возвращает количество строк в файле. Полезно для отображения состояния файла."""
    full_path = resolve_abs_path(path)
    text = full_path.read_text(encoding="utf-8", errors="ignore")
    total_lines = len(text.splitlines())
    return {"path": str(full_path), "total_lines": total_lines}
