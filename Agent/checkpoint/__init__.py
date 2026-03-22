import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

_DB_PATH: Optional[Path] = None
_DB_INITIALIZED = False


def _db() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        tca_dir = Path.cwd() / ".tca"
        tca_dir.mkdir(exist_ok=True)
        _DB_PATH = tca_dir / "checkpoints.sqlite"
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
    conn.commit()
    conn.close()
    return True
