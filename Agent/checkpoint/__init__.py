import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from Agent.runtime_paths import project_data_dir

_DB_PATH: Optional[Path] = None
_DB_INITIALIZED = False


def _db() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        data = project_data_dir()
        data.mkdir(parents=True, exist_ok=True)
        _DB_PATH = data / "checkpoints.sqlite"
    return _DB_PATH


def _init_db() -> None:
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return

    conn = sqlite3.connect(str(_db()))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            session_id TEXT PRIMARY KEY,
            messages_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS turn_snapshots (
            session_id TEXT NOT NULL,
            turn_index INTEGER NOT NULL,
            messages_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (session_id, turn_index)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS turn_workspace_snapshots (
            session_id TEXT NOT NULL,
            turn_index INTEGER NOT NULL,
            paths_json TEXT NOT NULL,
            snapshot_ts TEXT NOT NULL,
            PRIMARY KEY (session_id, turn_index)
        )
    """)
    rows = conn.execute("SELECT session_id, updated_at FROM checkpoints").fetchall()
    for sid, upd in rows:
        exists = conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (sid,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO sessions (session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (sid, f"chat-{sid}", upd, upd),
            )
    conn.commit()
    conn.close()
    _DB_INITIALIZED = True


def _tool_call_to_dict(tc: Any) -> Dict[str, Any]:
    """Normalize a tool call (LangChain ToolCall or dict) to a plain dict."""
    if isinstance(tc, dict):
        return {
            "name": tc.get("name", ""),
            "args": tc.get("args", {}),
            "id": tc.get("id", ""),
            "type": tc.get("type", "tool_call"),
        }
    return {
        "name": getattr(tc, "name", ""),
        "args": getattr(tc, "args", {}),
        "id": getattr(tc, "id", ""),
        "type": getattr(tc, "type", "tool_call"),
    }


def _message_to_dict(m: Any) -> Dict[str, Any]:
    """Приводит сообщение LangChain к простому dict для JSON."""
    if isinstance(m, dict):
        return m
    out: Dict[str, Any] = {
        "type": type(m).__name__,
        "content": getattr(m, "content", "") or "",
    }
    if hasattr(m, "tool_calls") and m.tool_calls:
        out["tool_calls"] = [_tool_call_to_dict(tc) for tc in m.tool_calls]
    if type(m).__name__ == "ToolMessage":
        out["tool_call_id"] = getattr(m, "tool_call_id", "") or ""
        nm = getattr(m, "name", None)
        if nm:
            out["name"] = nm
    return out


def save_state(messages: List[Any], session_id: str, title: str = "") -> None:
    """Сохраняет список сообщений (LangChain или dict) в SQLite."""
    from datetime import datetime
    _init_db()
    out = [_message_to_dict(m) for m in messages]
    raw = json.dumps(out, ensure_ascii=False)
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(str(_db()))
    row = conn.execute("SELECT created_at, title FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row:
        created_at, old_title = row
        final_title = (title or "").strip() or (old_title or f"chat-{session_id}")
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (final_title, now, session_id),
        )
    else:
        final_title = (title or "").strip() or f"chat-{session_id}"
        conn.execute(
            "INSERT INTO sessions (session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, final_title, now, now),
        )
    conn.execute(
        "INSERT OR REPLACE INTO checkpoints (session_id, messages_json, updated_at) VALUES (?, ?, ?)",
        (session_id, raw, now),
    )
    conn.commit()
    conn.close()


def load_state(session_id: str) -> Optional[List[Dict[str, Any]]]:
    """Загружает состояние из SQLite. Возвращает список dict (type, content, ...) или None."""
    _init_db()
    conn = sqlite3.connect(str(_db()))
    row = conn.execute(
        "SELECT messages_json FROM checkpoints WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return json.loads(row[0])


def create_session(title: str = "") -> str:
    """Создаёт новую сессию и возвращает session_id."""
    from datetime import datetime
    _init_db()
    sid = uuid4().hex[:10]
    now = datetime.utcnow().isoformat()
    t = (title or "").strip() or f"chat-{sid}"
    conn = sqlite3.connect(str(_db()))
    conn.execute(
        "INSERT INTO sessions (session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (sid, t, now, now),
    )
    conn.commit()
    conn.close()
    return sid


def list_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    """Список сохранённых чатов (последние сверху)."""
    _init_db()
    conn = sqlite3.connect(str(_db()))
    rows = conn.execute(
        "SELECT session_id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for sid, title, created_at, updated_at in rows:
        msg_row = conn.execute(
            "SELECT messages_json FROM checkpoints WHERE session_id = ?",
            (sid,),
        ).fetchone()
        msg_count = 0
        if msg_row and msg_row[0]:
            try:
                msg_count = len(json.loads(msg_row[0]))
            except Exception:
                msg_count = 0
        out.append(
            {
                "session_id": sid,
                "title": title,
                "created_at": created_at,
                "updated_at": updated_at,
                "message_count": msg_count,
            }
        )
    conn.close()
    return out


def delete_session(session_id: str) -> bool:
    """Удаляет чат (sessions + checkpoints)."""
    _init_db()
    conn = sqlite3.connect(str(_db()))
    conn.execute("DELETE FROM checkpoints WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM turn_snapshots WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM turn_workspace_snapshots WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    return True


def save_pre_turn_snapshot(session_id: str, turn_index: int, messages: List[Any]) -> None:
    """Состояние диалога до добавления turn_index-го пользовательского сообщения (0 = до первого Human)."""
    from datetime import datetime

    _init_db()
    out = [_message_to_dict(m) for m in messages]
    raw = json.dumps(out, ensure_ascii=False)
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(str(_db()))
    conn.execute(
        """
        INSERT OR REPLACE INTO turn_snapshots (session_id, turn_index, messages_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, int(turn_index), raw, now),
    )
    conn.commit()
    conn.close()


def load_pre_turn_snapshot(session_id: str, turn_index: int) -> Optional[List[Dict[str, Any]]]:
    _init_db()
    conn = sqlite3.connect(str(_db()))
    row = conn.execute(
        "SELECT messages_json FROM turn_snapshots WHERE session_id = ? AND turn_index = ?",
        (session_id, int(turn_index)),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return json.loads(row[0])


def delete_turn_snapshots_from(session_id: str, from_turn_index: int) -> None:
    """Удаляет снимки с turn_index >= from_turn_index (после отката)."""
    _init_db()
    conn = sqlite3.connect(str(_db()))
    conn.execute(
        "DELETE FROM turn_snapshots WHERE session_id = ? AND turn_index >= ?",
        (session_id, int(from_turn_index)),
    )
    conn.commit()
    conn.close()


def get_session_created_at(session_id: str) -> Optional[str]:
    """ISO created_at строки sessions (начало «жизни» чата для скоупа отката файлов)."""
    _init_db()
    conn = sqlite3.connect(str(_db()))
    row = conn.execute("SELECT created_at FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def _path_under_project(abs_path: str, project_root: Path) -> bool:
    try:
        p = Path(abs_path).resolve()
        r = project_root.resolve()
        return p == r or r in p.parents
    except Exception:
        return False


def workspace_mapping_for_turn(session_id: str, turn_index: int, project_root: Path) -> Dict[str, str]:
    """path→version_id: только под корнем проекта; turn_index>0 — только файлы с версией TCA не раньше created_at сессии."""
    try:
        from Agent.versioning import (
            latest_version_created_at,
            snapshot_all_paths_latest_version,
        )
    except ImportError:
        from versioning import (
            latest_version_created_at,
            snapshot_all_paths_latest_version,
        )

    full = snapshot_all_paths_latest_version()
    root = project_root.resolve()
    under: Dict[str, str] = {}
    for p, vid in full.items():
        if _path_under_project(p, root):
            under[p] = vid

    if int(turn_index) == 0:
        return under

    session_ts = get_session_created_at(session_id)
    if not session_ts:
        return under

    narrowed: Dict[str, str] = {}
    for p, vid in under.items():
        cat = latest_version_created_at(p)
        if cat and cat >= session_ts:
            narrowed[p] = vid
    return narrowed


def save_pre_turn_workspace_snapshot(session_id: str, turn_index: int) -> None:
    """Снимок path→version_id для отката: не глобально по всей БД, а по текущему проекту и (с 2-го хода) по файлам сессии."""
    from datetime import datetime

    try:
        from ..path_utils import get_project_root
    except ImportError:
        try:
            from Agent.path_utils import get_project_root
        except ImportError:
            from path_utils import get_project_root

    _init_db()
    snapshot_ts = datetime.utcnow().isoformat()
    mapping = workspace_mapping_for_turn(session_id, int(turn_index), get_project_root())
    raw = json.dumps(mapping, ensure_ascii=False)
    conn = sqlite3.connect(str(_db()))
    conn.execute(
        """
        INSERT OR REPLACE INTO turn_workspace_snapshots (session_id, turn_index, paths_json, snapshot_ts)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, int(turn_index), raw, snapshot_ts),
    )
    conn.commit()
    conn.close()


def delete_turn_workspace_snapshots_from(session_id: str, from_turn_index: int) -> None:
    _init_db()
    conn = sqlite3.connect(str(_db()))
    conn.execute(
        "DELETE FROM turn_workspace_snapshots WHERE session_id = ? AND turn_index >= ?",
        (session_id, int(from_turn_index)),
    )
    conn.commit()
    conn.close()


def restore_turn_workspace(session_id: str, turn_index: int) -> Dict[str, Any]:
    """Восстанавливает файлы по снимку turn_index: откат версий + удаление файлов, созданных после метки."""
    from pathlib import Path

    try:
        from Agent.versioning import paths_first_version_strictly_after, rollback_to_version
    except ImportError:
        from ..versioning import paths_first_version_strictly_after, rollback_to_version

    _init_db()
    conn = sqlite3.connect(str(_db()))
    row = conn.execute(
        "SELECT paths_json, snapshot_ts FROM turn_workspace_snapshots WHERE session_id = ? AND turn_index = ?",
        (session_id, int(turn_index)),
    ).fetchone()
    conn.close()
    if not row:
        return {"ok": False, "error": "no_workspace_snapshot"}
    paths_json, snapshot_ts = row[0], row[1]
    try:
        mapping: Dict[str, str] = json.loads(paths_json) if paths_json else {}
    except Exception:
        mapping = {}

    to_delete = paths_first_version_strictly_after(snapshot_ts)
    restored = 0
    failed: List[str] = []
    for path, vid in mapping.items():
        try:
            r = rollback_to_version(path, vid)
            if r.get("ok"):
                restored += 1
            else:
                failed.append(str(path))
        except Exception as ex:
            failed.append(f"{path}:{type(ex).__name__}")

    deleted = 0
    for path in to_delete:
        try:
            p = Path(path)
            if p.is_file():
                p.unlink()
                deleted += 1
        except Exception:
            pass

    return {
        "ok": True,
        "restored_files": restored,
        "deleted_new_files": deleted,
        "failed_paths": failed[:12],
        "snapshot_ts": snapshot_ts,
    }


def messages_from_stored_dicts(
    dicts: List[Dict[str, Any]],
    system_prompt: str,
) -> List[Any]:
    """Восстанавливает LangChain-сообщения из JSON checkpoint + свежий system prompt."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    try:
        from Agent.message_utils import sanitize_messages
    except ImportError:
        from message_utils import sanitize_messages

    restored: List[Any] = []
    for d in dicts:
        t = d.get("type", "")
        if t == "SystemMessage":
            continue
        if t == "HumanMessage":
            restored.append(HumanMessage(content=d.get("content", "") or ""))
        elif t == "AIMessage":
            restored.append(
                AIMessage(content=d.get("content", "") or "", tool_calls=d.get("tool_calls") or [])
            )
        elif t == "ToolMessage":
            restored.append(
                ToolMessage(
                    content=str(d.get("content", "")),
                    tool_call_id=d.get("tool_call_id", "") or "",
                    name=str(d.get("name", "") or ""),
                )
            )
    return sanitize_messages([SystemMessage(content=system_prompt)] + restored)
