"""Единый текст итога Creator Mode для TUI, classic CLI и истории сообщений."""
from __future__ import annotations

from typing import Any, Dict


def format_creator_summary_text(cr: Dict[str, Any]) -> str:
    """Markdown: статус, все воркеры, полный result (с защитными лимитами по длине)."""
    if not cr:
        return "Creator mode finished."
    orch = cr.get("orchestration") or ""
    orch_bit = f" | оркестрация: `{orch}`" if orch else ""
    lines = [
        f"**Creator mode** — {cr.get('status', '?')} | "
        f"workers OK: {cr.get('workers_done', 0)}/{cr.get('workers_total', 0)} | "
        f"{cr.get('elapsed', 0):.1f}s{orch_bit}",
    ]
    sup = (cr.get("supervisor_synthesis") or "").strip()
    if sup:
        if len(sup) > 120_000:
            sup = sup[:119_997] + "…"
        lines.append("\n### Сводка супервайзера\n" + sup)
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
