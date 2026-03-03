"""Инструменты плана: модель может создать план, обновлять статусы и продолжать выполнение.

Устойчиво к повторным save_plan(): сохраняет статусы, не сбрасывает прогресс.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.tools import tool


def _plan_path() -> Path:
    return Path.cwd() / ".tca_plan.json"


def _load_raw() -> Dict[str, Any]:
    if not _plan_path().exists():
        return {}
    try:
        return json.loads(_plan_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_raw(data: Dict[str, Any]) -> None:
    _plan_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@tool
def save_plan(title: str, steps: List[str]) -> Dict[str, Any]:
    """Сохраняет план (список шагов) для текущей задачи. Используй перед выполнением большой задачи."""
    now = datetime.utcnow().isoformat()
    prev = _load_raw()
    prev_steps = prev.get("steps", []) if isinstance(prev, dict) else []
    prev_by_text = {str(s.get("text", "")): s for s in prev_steps if isinstance(s, dict)}

    new_steps = []
    for i, s in enumerate(steps):
        s_text = str(s)
        prev_s = prev_by_text.get(s_text)
        if prev_s:
            new_steps.append(
                {
                    "i": i,
                    "text": s_text,
                    "status": prev_s.get("status", "pending"),
                    "note": prev_s.get("note", ""),
                }
            )
        else:
            new_steps.append({"i": i, "text": s_text, "status": "pending", "note": ""})

    data = {
        "title": title.strip() or prev.get("title") or "План",
        "created_at": prev.get("created_at") or now,
        "updated_at": now,
        "steps": new_steps,
    }
    _save_raw(data)
    return {"ok": True, "plan_path": str(_plan_path()), "step_count": len(new_steps)}


@tool
def load_plan() -> Dict[str, Any]:
    """Загружает текущий план (если есть)."""
    data = _load_raw()
    return {"ok": bool(data), "plan": data}


@tool
def update_plan(step_index: int, status: str, note: str = "") -> Dict[str, Any]:
    """Обновляет статус шага плана. status: pending | in_progress | completed | blocked."""
    data = _load_raw()
    if not data or "steps" not in data:
        return {"ok": False, "error": "no_plan"}
    steps = data.get("steps", [])
    n = len(steps)
    if step_index < 0:
        return {"ok": False, "error": "bad_index", "max_index": n - 1}
    # Поддержка 1-based индекса (частая ошибка моделей): если step_index == n → это последний шаг.
    idx = step_index
    if n > 0 and step_index == n:
        idx = n - 1
    if idx >= n:
        return {"ok": False, "error": "bad_index", "max_index": n - 1}
    st = (status or "").strip().lower()
    if st not in ("pending", "in_progress", "completed", "blocked"):
        return {"ok": False, "error": "bad_status"}
    steps[idx]["status"] = st
    if note:
        steps[idx]["note"] = note[:500]
    data["updated_at"] = datetime.utcnow().isoformat()
    data["steps"] = steps
    _save_raw(data)
    return {"ok": True, "plan_path": str(_plan_path()), "step_index": idx, "status": st}


@tool
def clear_plan() -> Dict[str, Any]:
    """Удаляет текущий план."""
    try:
        if _plan_path().exists():
            try:
                ans = input("  Удалить текущий план? [y/N] > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans not in ("y", "yes", "да", "д"):
                return {"ok": False, "skipped": True, "reason": "user_cancelled"}
            _plan_path().unlink()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)}

