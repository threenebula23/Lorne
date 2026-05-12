"""Вторая часть Deep Solver: основной цикл в :mod:`Agent.deep_solver.legacy_loop`.

Состояние чекпоинтов остаётся в :mod:`Agent.deep_solver._impl_a`; после загрузки
легаси-модуля подменяем ``register_checkpoint`` / ``list_checkpoints`` на реализацию
из ``_impl_a``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, List

from . import _impl_a

_LEGACY: Any = None


def _load_legacy_loop_module() -> Any:
    global _LEGACY
    if _LEGACY is not None:
        return _LEGACY
    legacy_path = Path(__file__).resolve().parent / "legacy_loop.py"
    spec = importlib.util.spec_from_file_location(
        "lorne_agent_deep_solver_legacy", legacy_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Deep Solver legacy from {legacy_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.register_checkpoint = _impl_a.register_checkpoint
    mod.get_checkpoint = _impl_a.get_checkpoint
    mod.clear_checkpoint = _impl_a.clear_checkpoint
    mod.list_checkpoints = _impl_a.list_checkpoints
    _LEGACY = mod
    return mod


def run_deep_solver(*args: Any, **kwargs: Any) -> Any:
    return _load_legacy_loop_module().run_deep_solver(*args, **kwargs)


def apply_checkpoint_action(
    cp_id: str,
    action: str,
    messages: List[Any],
    enhanced_system_prompt: str,
    session_id: str,
    bridge: Any,
) -> Dict[str, Any]:
    """Rollback / continue from a Deep checkpoint (uses shared index in ``_impl_a``)."""
    try:
        from Agent.checkpoint import (
            delete_turn_snapshots_from,
            delete_turn_workspace_snapshots_from,
            load_pre_turn_snapshot,
            messages_from_stored_dicts,
            restore_turn_workspace,
            save_state,
        )
    except ImportError:
        from checkpoint import (
            delete_turn_snapshots_from,
            delete_turn_workspace_snapshots_from,
            load_pre_turn_snapshot,
            messages_from_stored_dicts,
            restore_turn_workspace,
            save_state,
        )

    entry = _impl_a.get_checkpoint(cp_id)
    if not entry:
        return {"ok": False, "error": "checkpoint_not_found"}

    turn_index = int(entry.get("turn_index") or 0)
    sess = str(entry.get("session_id") or session_id)

    try:
        raw = load_pre_turn_snapshot(sess, turn_index)
        if not raw:
            return {"ok": False, "error": "no_snapshot"}
        restored = messages_from_stored_dicts(raw, enhanced_system_prompt)
        messages.clear()
        messages.extend(restored)
        ws = restore_turn_workspace(sess, turn_index)
        delete_turn_snapshots_from(sess, turn_index)
        delete_turn_workspace_snapshots_from(sess, turn_index)
        save_state(messages, session_id=sess)
        try:
            bridge.on_chat_reload_messages(list(messages))
        except Exception:
            pass
        try:
            bridge.on_file_changed("")
        except Exception:
            pass
        _impl_a.clear_checkpoint(cp_id)
        result: Dict[str, Any] = {
            "ok": True,
            "action": action,
            "turn_index": turn_index,
            "workspace": ws if isinstance(ws, dict) else {},
            "checkpoint_title": str(entry.get("title") or ""),
            "checkpoint_id": cp_id,
        }
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}
