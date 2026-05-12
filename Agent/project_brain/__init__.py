"""Project Brain: static scan + Markdown output for RAG (optional Relator)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .scanner import scan_project
from .build import build_brain_markdown
from .context_builder import build_project_context
from .agent_architecture import (
    AGENT_ARCHITECTURE_FILE,
    reindex_brain_rag,
    write_agent_architecture,
    write_brain_markdown,
)


def refresh_project_brain(root: Path | None = None) -> Dict[str, Any]:
    """Scan ``root``, write ``project_brain/**``, return summary paths."""
    if root is None:
        try:
            from Agent.path_utils import get_project_root

            r = get_project_root().resolve()
        except Exception:
            r = Path.cwd().resolve()
    else:
        r = Path(root).resolve()
    data = scan_project(r)
    paths = build_brain_markdown(r, data)
    return {"root": str(r), "written": [str(p) for p in paths], "context": build_project_context(data, r)}
