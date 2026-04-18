"""Единый текст итога Creator Mode для TUI, classic CLI и истории сообщений."""
from __future__ import annotations

from typing import Any, Dict


def format_creator_summary_text(cr: Dict[str, Any]) -> str:
    """Markdown: статус, все воркеры, полный result (с защитными лимитами по длине)."""
    if not cr:
        return "Creator mode finished."
    lines = [
        f"**Creator mode** — {cr.get('status', '?')} | "
        f"workers OK: {cr.get('workers_done', 0)}/{cr.get('workers_total', 0)} | "
        f"{cr.get('elapsed', 0):.1f}s",
    ]
    for r in cr.get("results", []) or []:
        wid = r.get("worker_id", "?")
        st = r.get("status", "?")
        res = str(r.get("result", ""))
        if len(res) > 450_000:
            res = res[:449_997] + "…"
        lines.append(f"\n### {wid} ({st})\n{res}")
    out = "\n".join(lines)
    if len(out) > 500_000:
        out = out[:499_997] + "…"
    return out
