"""`download_file` — pull an image / archive / dataset from an HTTP(S) URL.

Built on stdlib ``urllib.request`` so there are no extra dependencies.
Designed to be safe for the TUI:

* Streams in 64 KiB chunks so huge files don't blow the Python heap.
* Emits progress ticks via :meth:`Interface.tui_bridge.TUIBridge.on_download_progress`
  — the chat panel materialises a dedicated :class:`DownloadProgressBlock`
  widget that shows % / size / throughput / ETA and a Cancel button.
* Honours the bridge's stop flag and a per-download cancellation flag so
  the cancel button really stops the read loop.
* Refuses to write outside the project workspace (``resolve_abs_path``)
  and caps the on-disk size at ``max_bytes`` (default 200 MiB).

The tool returns a rich dict with ``status`` / ``path`` / ``bytes`` /
``elapsed_seconds`` / ``url`` / ``content_type`` that the TUI's tool-card
renderer turns into a pretty summary with an elapsed timer.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from langchain_core.tools import tool

try:
    from ..path_utils import resolve_abs_path
except ImportError:  # pragma: no cover
    def resolve_abs_path(path_str: str) -> Path:
        p = Path(path_str).expanduser()
        return (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()


# ─── Cancellation registry ────────────────────────────────────────────
#
# When the user clicks "Отменить" on a DownloadProgressBlock, the UI
# calls :func:`cancel_download` with the block's ``download_id`` which
# flips the matching flag below; the streaming loop notices on the next
# chunk boundary and aborts cleanly.

_CANCEL_FLAGS: Dict[str, threading.Event] = {}
_CANCEL_LOCK = threading.Lock()


def _register_cancel_flag(download_id: str) -> threading.Event:
    with _CANCEL_LOCK:
        ev = _CANCEL_FLAGS.get(download_id)
        if ev is None:
            ev = threading.Event()
            _CANCEL_FLAGS[download_id] = ev
        return ev


def cancel_download(download_id: str) -> bool:
    """UI-facing: mark a download as cancelled. Returns True if a live
    download was found, False otherwise."""
    with _CANCEL_LOCK:
        ev = _CANCEL_FLAGS.get(download_id)
    if ev is None:
        return False
    ev.set()
    return True


def _clear_cancel_flag(download_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCEL_FLAGS.pop(download_id, None)


# ─── Helpers ──────────────────────────────────────────────────────────

try:
    from Interface.branding import user_agent_fragment
    _DEFAULT_UA = f"Mozilla/5.0 ({user_agent_fragment()}; download_file)"
except Exception:
    _DEFAULT_UA = "Mozilla/5.0 (Lorne download_file tool)"
_MAX_BYTES_DEFAULT = 200 * 1024 * 1024  # 200 MiB
_CHUNK = 64 * 1024


def _safe_filename_from_url(url: str, fallback: str = "download") -> str:
    try:
        parsed = urlparse(url)
        base = os.path.basename(parsed.path) or ""
    except Exception:
        base = ""
    if not base or base in (".", "/"):
        base = fallback
    base = base.split("?", 1)[0].split("#", 1)[0]
    # Strip path separators defensively.
    base = base.replace("\\", "_").replace("/", "_")
    return base[:200] or fallback


def _bridge() -> Optional[Any]:
    try:
        from Interface.tui_bridge import get_bridge
        return get_bridge()
    except Exception:
        return None


# ─── Tool ─────────────────────────────────────────────────────────────

@tool
def download_file(url: str, dest: str = "", max_bytes: int = 0,
                  timeout_seconds: int = 60) -> Dict[str, Any]:
    """HTTP(S) загрузка в workspace; dest пустой → ./downloads/<basename>; max_bytes 0 = 200 МиБ; прогресс/отмена в TUI."""
    u = str(url or "").strip()
    if not u or not u.lower().startswith(("http://", "https://")):
        return {"status": "error", "error": "invalid_url",
                "hint": "ожидается http(s)://...", "url": u}

    filename = _safe_filename_from_url(u)
    if dest:
        target = resolve_abs_path(dest)
        if target.is_dir() or str(dest).rstrip("/").endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            target = target / filename
    else:
        downloads = resolve_abs_path("downloads")
        downloads.mkdir(parents=True, exist_ok=True)
        target = downloads / filename

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"status": "error", "error": f"mkdir: {e}",
                "path": str(target), "url": u}

    cap = int(max_bytes) if max_bytes and max_bytes > 0 else _MAX_BYTES_DEFAULT
    download_id = f"dl_{uuid.uuid4().hex[:10]}"
    cancel_event = _register_cancel_flag(download_id)
    bridge = _bridge()
    t0 = time.time()

    try:
        req = Request(u, headers={"User-Agent": _DEFAULT_UA})
        with urlopen(req, timeout=timeout_seconds) as resp:
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            total_str = resp.headers.get("Content-Length")
            total = int(total_str) if total_str and total_str.isdigit() else 0

            if bridge is not None:
                try:
                    bridge.on_download_progress(
                        download_id=download_id, url=u,
                        received_bytes=0, total_bytes=total,
                        elapsed=0.0, done=False,
                    )
                except Exception:
                    pass

            received = 0
            last_emit = 0.0
            with open(target, "wb") as out:
                while True:
                    if cancel_event.is_set():
                        status = "cancelled"
                        error = "user_cancelled"
                        break
                    # Also honour the global stop button on the TUI.
                    if bridge is not None and getattr(bridge,
                                                     "is_stop_requested",
                                                     lambda: False)():
                        status = "cancelled"
                        error = "stop_requested"
                        break
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        status = "ok"
                        error = ""
                        break
                    received += len(chunk)
                    if received > cap:
                        status = "error"
                        error = f"exceeds_max_bytes ({cap})"
                        break
                    out.write(chunk)
                    now = time.time()
                    if bridge is not None and now - last_emit >= 0.2:
                        last_emit = now
                        try:
                            bridge.on_download_progress(
                                download_id=download_id, url=u,
                                received_bytes=received, total_bytes=total,
                                elapsed=now - t0, done=False,
                            )
                        except Exception:
                            pass

        elapsed = round(time.time() - t0, 3)

        if status != "ok":
            try:
                if target.exists():
                    target.unlink()
            except Exception:
                pass

        if bridge is not None:
            try:
                bridge.on_download_progress(
                    download_id=download_id, url=u,
                    received_bytes=received, total_bytes=total,
                    elapsed=elapsed, done=True,
                    error=("" if status == "ok" else error),
                )
            except Exception:
                pass

        return {
            "status": status,
            "path": str(target) if status == "ok" else "",
            "bytes": int(received),
            "total_bytes": int(total or 0),
            "elapsed_seconds": elapsed,
            "url": u,
            "content_type": content_type,
            "error": error or None,
            "download_id": download_id,
        }

    except (HTTPError, URLError) as e:
        elapsed = round(time.time() - t0, 3)
        if bridge is not None:
            try:
                bridge.on_download_progress(
                    download_id=download_id, url=u,
                    received_bytes=0, total_bytes=0,
                    elapsed=elapsed, done=True, error=str(e),
                )
            except Exception:
                pass
        return {"status": "error", "error": str(e), "url": u,
                "elapsed_seconds": elapsed, "download_id": download_id}
    except Exception as e:
        elapsed = round(time.time() - t0, 3)
        if bridge is not None:
            try:
                bridge.on_download_progress(
                    download_id=download_id, url=u,
                    received_bytes=0, total_bytes=0,
                    elapsed=elapsed, done=True, error=str(e),
                )
            except Exception:
                pass
        return {"status": "error", "error": f"{type(e).__name__}: {e}",
                "url": u, "elapsed_seconds": elapsed,
                "download_id": download_id}
    finally:
        _clear_cancel_flag(download_id)
