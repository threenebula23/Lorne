"""Инструменты генерации кода: запись в файл с правильным расширением."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

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


_LANG_TO_EXT = {
    # Python
    "python": ".py",
    "py": ".py",
    # JS/TS
    "javascript": ".js",
    "js": ".js",
    "node": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "tsx": ".tsx",
    "jsx": ".jsx",
    "react": ".tsx",
    # Web
    "html": ".html",
    "css": ".css",
    "json": ".json",
    "yaml": ".yml",
    "yml": ".yml",
    "toml": ".toml",
    "markdown": ".md",
    "md": ".md",
    # Systems
    "go": ".go",
    "golang": ".go",
    "rust": ".rs",
    "rs": ".rs",
    "java": ".java",
    "kotlin": ".kt",
    "kt": ".kt",
    "c": ".c",
    "cpp": ".cpp",
    "c++": ".cpp",
    "cxx": ".cpp",
    "csharp": ".cs",
    "cs": ".cs",
    "ruby": ".rb",
    "rb": ".rb",
    "php": ".php",
    "sql": ".sql",
    "bash": ".sh",
    "sh": ".sh",
    "powershell": ".ps1",
    "ps1": ".ps1",
}


def _normalize_language(language: str) -> str:
    return (language or "").strip().lower()


def _choose_extension(language: str) -> Optional[str]:
    lang = _normalize_language(language)
    if not lang:
        return None
    return _LANG_TO_EXT.get(lang)


def _apply_extension(path: Path, ext: Optional[str]) -> Path:
    # Dockerfile special-case
    if path.name.lower() == "dockerfile":
        return path
    if ext is None:
        return path
    # If no suffix, add one
    if path.suffix == "":
        return path.with_suffix(ext)
    # If .txt was used for code, replace with language extension
    if path.suffix.lower() == ".txt":
        return path.with_suffix(ext)
    return path


def _normalize_code_text(text: str) -> str:
    """Нормализует текст кода, если модель передала литералы '\\n' вместо переводов строк."""
    if not isinstance(text, str):
        return str(text)
    # Если реальных переводов строк нет, но встречается '\\n' — вероятно строка двойно-экранирована.
    if "\n" not in text and "\\n" in text:
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
        # Часто вместе с \\n идут табы
        text = text.replace("\\t", "\t")
    return text


@tool
def create_code_file(filepath: str, language: str, code: str) -> Dict[str, Any]:
    """Создаёт/перезаписывает файл с кодом. Если filepath без расширения — добавит расширение по language.
    Если filepath оканчивается на .txt, но language указывает на код — заменит на расширение языка."""
    raw_path = resolve_abs_path(filepath)
    ext = _choose_extension(language)
    final_path = _apply_extension(raw_path, ext)
    before_text = ""
    before_total_lines = 0
    snapshot_id = ""
    if final_path.exists():
        before_text = final_path.read_text(encoding="utf-8", errors="ignore")
        before_total_lines = len(before_text.splitlines())
        snapshot_id = save_version(str(final_path), before_text, note="before-create_code_file") or ""
    final_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_code_text(code)
    final_path.write_text(normalized, encoding="utf-8")
    total_lines = len(normalized.splitlines())
    return {
        "path": str(final_path),
        "action": "code_written",
        "language": _normalize_language(language),
        "extension": final_path.suffix,
        "total_lines": total_lines,
        "before_total_lines": before_total_lines,
        "after_total_lines": total_lines,
        "delta_total_lines": total_lines - before_total_lines,
        "snapshot_id": snapshot_id,
    }


@tool
def append_code_snippet(filepath: str, snippet: str, language: str = "") -> Dict[str, Any]:
    """Добавляет сниппет кода в конец файла. Если файла нет — создаст. Расширение добавит по language, если его нет."""
    raw_path = resolve_abs_path(filepath)
    ext = _choose_extension(language)
    final_path = _apply_extension(raw_path, ext)
    snippet = _normalize_code_text(snippet)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        prev = final_path.read_text(encoding="utf-8", errors="ignore")
        snapshot_id = save_version(str(final_path), prev, note="before-append_code_snippet") or ""
        before_total_lines = len(prev.splitlines())
        new = prev
        if new and not new.endswith("\n"):
            new += "\n"
        new += snippet
    else:
        snapshot_id = ""
        before_total_lines = 0
        new = snippet
    final_path.write_text(new, encoding="utf-8")
    total_lines = len(new.splitlines())
    return {
        "path": str(final_path),
        "action": "snippet_appended",
        "language": _normalize_language(language),
        "extension": final_path.suffix,
        "total_lines": total_lines,
        "before_total_lines": before_total_lines,
        "after_total_lines": total_lines,
        "delta_total_lines": total_lines - before_total_lines,
        "snapshot_id": snapshot_id,
    }

