"""Версионирование файлов для отката правок (SQLite).

Сохраняет снимки содержимого файла перед записью, чтобы можно было откатиться.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _db_path() -> Path:
    return Path.cwd() / ".tca_versions.sqlite"


def _init_db() -> None:
    conn = sqlite3.connect(str(_db_path()))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_versions (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            note TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_versions_path ON file_versions(path)")
    conn.commit()
    conn.close()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def save_version(path: str, content: str, note: str = "") -> str:
    """Сохраняет версию содержимого файла. Возвращает version_id."""
    _init_db()
    p = str(Path(path).resolve())
    ts = datetime.utcnow().isoformat()
    sha = _sha256(content)
    # Детерминированный id, чтобы одинаковые снимки не плодились
    vid = hashlib.sha256(f"{p}|{sha}|{ts}".encode("utf-8")).hexdigest()[:16]
    conn = sqlite3.connect(str(_db_path()))
    conn.execute(
        "INSERT OR REPLACE INTO file_versions (id, path, sha256, content, created_at, note) VALUES (?, ?, ?, ?, ?, ?)",
        (vid, p, sha, content, ts, note),
    )
    conn.commit()
    conn.close()
    return vid


def list_versions(path: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Список версий для файла (последние сначала)."""
    _init_db()
    p = str(Path(path).resolve())
    conn = sqlite3.connect(str(_db_path()))
    rows = conn.execute(
        "SELECT id, sha256, created_at, note FROM file_versions WHERE path = ? ORDER BY created_at DESC LIMIT ?",
        (p, limit),
    ).fetchall()
    conn.close()
    return [{"id": r[0], "sha256": r[1], "created_at": r[2], "note": r[3] or ""} for r in rows]


def get_version_content(path: str, version_id: str) -> Optional[str]:
    _init_db()
    p = str(Path(path).resolve())
    conn = sqlite3.connect(str(_db_path()))
    row = conn.execute(
        "SELECT content FROM file_versions WHERE path = ? AND id = ?",
        (p, version_id),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def rollback_to_version(path: str, version_id: str) -> Dict[str, Any]:
    """Откат файла к конкретной версии."""
    p = Path(path).resolve()
    content = get_version_content(str(p), version_id)
    if content is None:
        return {"ok": False, "error": "version_not_found", "path": str(p), "version_id": version_id}
    if p.exists():
        current = p.read_text(encoding="utf-8", errors="ignore")
        save_version(str(p), current, note=f"auto-before-rollback->{version_id}")
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(p), "rolled_back_to": version_id, "total_lines": len(content.splitlines())}


def rollback_last(path: str) -> Dict[str, Any]:
    """Откат к самой последней сохранённой версии."""
    versions = list_versions(path, limit=1)
    if not versions:
        return {"ok": False, "error": "no_versions", "path": str(Path(path).resolve())}
    return rollback_to_version(path, versions[0]["id"])

