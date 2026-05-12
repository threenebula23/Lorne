"""Thinking and analysis tools for the Lorne agent.

Provides structured reasoning, diff visualization, and code analysis
that integrate with the TUI bridge for display.
"""
from __future__ import annotations

import difflib
from typing import Any, Dict, List

from langchain_core.tools import tool


@tool
def think(thought: str) -> Dict[str, Any]:
    """Краткая запись рассуждения; отображается в панели Thoughts."""
    try:
        from Interface.tui_bridge import get_bridge
        bridge = get_bridge()
        if bridge:
            bridge.on_thought(thought)
    except Exception:
        pass

    return {
        "recorded": True,
        "thought": thought,
        "note": "Мысль записана. Продолжай выполнение задачи.",
    }


@tool
def show_diff(path: str, old_content: str, new_content: str) -> Dict[str, Any]:
    """Unified diff old_content vs new_content для path (визуализация перед edit_file)."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
        lineterm="",
    ))

    additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    diff_text = "\n".join(diff)

    try:
        from Interface.tui_bridge import get_bridge
        bridge = get_bridge()
        if bridge:
            bridge.on_diff(old_content, new_content, path)
    except Exception:
        pass

    return {
        "path": path,
        "diff": diff_text[:5000],
        "additions": additions,
        "deletions": deletions,
        "changes": additions + deletions,
    }


@tool
def analyze_code(path: str, query: str) -> Dict[str, Any]:
    """Анализировать код в файле с использованием RAG.
    Находит релевантные чанки кода и возвращает их с контекстом.
    path — путь к файлу, query — что именно анализировать."""
    try:
        from Agent.rag import query as rag_query
    except ImportError:
        return {"error": "RAG модуль не доступен"}

    combined_query = f"{path} {query}"
    hits = rag_query(combined_query, top_k=5)

    path_hits = [h for h in hits if path in h.get("path", "")]
    if not path_hits:
        path_hits = hits

    try:
        from Agent.tools.file_ops import read_file
        file_result = read_file.invoke({"filename": path, "offset": 0, "limit": 50})
        file_header = file_result.get("content", "")[:500]
        total_lines = file_result.get("total_lines", 0)
    except Exception:
        file_header = ""
        total_lines = 0

    try:
        from Interface.tui_bridge import get_bridge
        bridge = get_bridge()
        if bridge:
            bridge.on_thought(f"Анализирую {path}: {query}")
            for hit in path_hits[:2]:
                bridge.on_code(
                    hit.get("snippet", ""),
                    "python" if path.endswith(".py") else "text",
                    f"{path}:{hit.get('start_line', '?')}-{hit.get('end_line', '?')}",
                )
    except Exception:
        pass

    return {
        "path": path,
        "query": query,
        "total_lines": total_lines,
        "header": file_header,
        "relevant_chunks": [
            {
                "lines": f"{h.get('start_line', '?')}-{h.get('end_line', '?')}",
                "score": h.get("score", 0),
                "snippet": h.get("snippet", "")[:500],
            }
            for h in path_hits[:5]
        ],
        "rag_hits_total": len(hits),
    }
