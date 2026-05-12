"""Model-authored Markdown under ``project_brain/`` (RAG-indexed, mostly not touched by refresh)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

AGENT_ARCHITECTURE_FILE = "agent_architecture.md"

# Корневые файлы, которые пересобирает сканер / Relator — не перезаписывать моделью напрямую.
_SCANNER_ROOT_FILES = frozenset({
    "overview.md",
    "architecture.md",
    "glossary.md",
    "tools.md",
    "flows.md",
    "rag_manifest.json",
})

_DENIED_PREFIXES = ("modules/", "machine/", "services/", "agents/")

_REL_SAFE = re.compile(r"^[A-Za-z0-9_.\-/]+$")


def _brain_root(root: Path | None) -> Path:
    if root is not None:
        return Path(root).resolve()
    try:
        from Agent.path_utils import get_project_root

        return get_project_root().resolve()
    except Exception:
        return Path.cwd().resolve()


def _is_allowed_brain_rel(rel: str) -> bool:
    """Куда модели разрешено писать Markdown (refresh не затирает ``agent/**``)."""
    if rel == AGENT_ARCHITECTURE_FILE:
        return True
    if rel.startswith("agent/") and rel.endswith(".md"):
        return True
    if "/" not in rel and rel.endswith(".md"):
        if rel.endswith("_notes.md") or rel.endswith("_supplement.md"):
            return True
    return False


def write_brain_markdown(
    root: Path | None,
    rel_path: str,
    content: str,
    *,
    mode: str = "append",
) -> Path:
    """Записать или дополнить ``project_brain/<rel_path>`` (только .md, без выхода из каталога).

    Разрешённые пути см. :func:`_is_allowed_brain_rel`. Запрещены корневые
    ``overview.md`` / ``architecture.md`` и деревья ``modules/`` … — для них
    используй ``agent/overview_notes.md``, ``agent/architecture_supplement.md`` и т.п.
    """
    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError("brain_rel_path_required")
    if ".." in rel.split("/"):
        raise ValueError("brain_rel_path_invalid")
    if not rel.endswith(".md"):
        raise ValueError("only_markdown")
    if not _REL_SAFE.match(rel):
        raise ValueError("brain_rel_path_chars")
    low = rel.lower()
    if rel in _SCANNER_ROOT_FILES or low == "rag_manifest.json":
        raise ValueError(
            f"protected_file:{rel} — пиши в agent/{rel.replace('.md', '')}_notes.md "
            "или agent/<имя>.md (подкаталог agent/ не пересобирается сканером)."
        )
    for pref in _DENIED_PREFIXES:
        if low.startswith(pref):
            raise ValueError(
                f"protected_prefix:{pref} — дополняй через agent/…_notes.md рядом по смыслу."
            )
    if not _is_allowed_brain_rel(rel):
        raise ValueError(
            "brain_rel_path_not_allowed — допустимо: agent/…/*.md, "
            "*_notes.md и *_supplement.md в корне project_brain/, "
            f"или {AGENT_ARCHITECTURE_FILE}."
        )

    body = (content or "").strip()
    if not body:
        raise ValueError("content_required")

    root = _brain_root(root)
    brain = root / "project_brain"
    brain.mkdir(parents=True, exist_ok=True)
    dest = (brain / rel).resolve()
    try:
        dest.relative_to(brain.resolve())
    except ValueError as e:
        raise ValueError("path_escape") from e

    m = (mode or "append").strip().lower()
    if m not in ("append", "replace"):
        raise ValueError("bad_write_mode")

    if m == "replace":
        if rel == AGENT_ARCHITECTURE_FILE:
            text = (
                "# Architecture (agent)\n\n"
                "_Сводка архитектуры и решений, записанная ассистентом. "
                "Файл не пересобирается автоматическим refresh._\n\n"
                f"{body}\n"
            )
        else:
            text = body + ("\n" if not body.endswith("\n") else "")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return dest

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    block = f"\n\n## Заметка ({stamp})\n\n{body}\n"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        prev = dest.read_text(encoding="utf-8", errors="replace")
    else:
        if rel == AGENT_ARCHITECTURE_FILE:
            prev = (
                "# Architecture (agent)\n\n"
                "_Накопленные заметки модели о структуре проекта. "
                "Не затираются ``project_brain_tool`` refresh._\n"
            )
        else:
            title = rel.split("/")[-1].replace(".md", "").replace("_", " ").strip() or rel
            prev = f"# {title}\n\n_Файл дополняется ассистентом; не трогается refresh в ``agent/**``._\n"
    dest.write_text(prev.rstrip() + block, encoding="utf-8")
    return dest


def write_agent_architecture(
    root: Path | None,
    content: str,
    *,
    mode: str = "append",
) -> Path:
    """Совместимость: то же, что ``write_brain_markdown(..., agent_architecture.md, ...)``."""
    return write_brain_markdown(root, AGENT_ARCHITECTURE_FILE, content, mode=mode)


def reindex_brain_rag(root: Path | None = None) -> int:
    """Reload brain chunks from disk into the in-process RAG store."""
    from Agent.rag import index_project_brain

    r = _brain_root(root)
    return index_project_brain(str(r))


def run_brain_sync_if_enabled(root: Path | None = None) -> int:
    """Reindex brain docs after an agent turn (respect ``LORNE_SKIP_BRAIN_SYNC``)."""
    import os

    flag = os.environ.get("LORNE_SKIP_BRAIN_SYNC", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return -1
    return reindex_brain_rag(root)
