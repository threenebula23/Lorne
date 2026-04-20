"""Shared styling helpers for ModalScreens (dialogs / popups).

Goals:
- Apply the current theme's accent colour to dialog borders / titles without
  requiring users to restart the app.
- Keep consistent spacing (padding / margins) across every dialog so they
  feel like part of the same design system as the main window.

Usage (inside a `ModalScreen`):

    from Interface.modal_style import apply_accent_to, MODAL_SHARED_CSS

    class MyDialog(ModalScreen):
        DEFAULT_CSS = MODAL_SHARED_CSS + '''
            #my-container { width: 72; ... }
        '''

        def on_mount(self) -> None:
            apply_accent_to(self, container_id="my-container", title_id="my-title")
"""
from __future__ import annotations

from typing import Iterable, Optional

from rich.text import Text


ACCENT_FALLBACK = "#8B5CF6"


def current_accent() -> str:
    try:
        from Interface.ui_prefs import load_prefs
        from Interface.themes import get_theme
        prefs = load_prefs()
        theme = get_theme(str(prefs.get("theme", "Purple Dark")))
        return str(prefs.get("accent_color") or theme.get("accent") or ACCENT_FALLBACK)
    except Exception:
        return ACCENT_FALLBACK


MODAL_SHARED_CSS = """
/* Shared look-and-feel for all ModalScreen popups. */
.modal-card {
    background: #151520;
    border: round #2D2D3D;
    padding: 1 2;
}
.modal-card > * {
    height: auto;
}
.modal-title {
    height: auto;
    text-style: bold;
    margin: 0 0 1 0;
    padding: 0;
}
.modal-section {
    height: auto;
    margin: 0 0 1 0;
    padding: 0;
}
.modal-row {
    height: auto;
    layout: horizontal;
    margin: 0 0 1 0;
}
.modal-row Button {
    min-width: 14;
    margin: 0 1 0 0;
    height: 3;
}
.modal-row Input {
    width: 1fr;
    margin: 0 1 0 0;
    background: #0D0D0D;
    color: #E5E7EB;
    border: solid #2D2D3D;
}
.modal-scroll {
    height: auto;
    max-height: 30;
    min-height: 2;
    margin: 0 0 1 0;
    border: solid #2D2D3D;
    background: #12121A;
    padding: 0 1;
}
.modal-footer {
    height: auto;
    layout: horizontal;
    margin: 1 0 0 0;
}
.modal-footer Button {
    min-width: 14;
    margin: 0 1 0 0;
    height: 3;
}
"""


def _set(widget, **kwargs) -> None:
    for attr, val in kwargs.items():
        try:
            setattr(widget.styles, attr, val)
        except Exception:
            pass


def apply_accent_to(
    screen,
    *,
    container_id: Optional[str] = None,
    title_id: Optional[str] = None,
    title_text: Optional[str] = None,
    extra_accent_ids: Iterable[str] = (),
) -> None:
    """Paint the accent colour onto a modal's container border and title label.

    This is called from ``on_mount`` so the popup matches the user's current
    theme immediately (no app restart needed).
    """
    accent = current_accent()
    if container_id:
        try:
            c = screen.query_one(f"#{container_id}")
            _set(c, border=("round", accent))
        except Exception:
            pass
    if title_id:
        try:
            t = screen.query_one(f"#{title_id}")
            if title_text is None:
                try:
                    cur = t.renderable
                    title_text = cur.plain if hasattr(cur, "plain") else str(cur)
                except Exception:
                    title_text = ""
            t.update(Text(title_text or "", style=f"bold {accent}"))
        except Exception:
            pass
    for wid in extra_accent_ids:
        try:
            w = screen.query_one(f"#{wid}")
            _set(w, color=accent)
        except Exception:
            pass
