"""Version Control panel — branch management + commit history with file selection."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from rich.text import Text

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, Checkbox, Input, Label, Static,
    TabbedContent, TabPane, Tree,
)
from textual.message import Message


class BranchSwitched(Message):
    def __init__(self, branch: str) -> None:
        super().__init__()
        self.branch = branch


class VersionControlPanel(Vertical):
    """Left lower panel — branches + commit history with git staging."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._gm = None
        self._staged_files: Set[str] = set()
        self._branch_order: List[str] = []

    def compose(self) -> ComposeResult:
        with TabbedContent("Branches", "History"):
            with TabPane("Branches", id="tab-branches"):
                yield VerticalScroll(id="branches-content")
            with TabPane("History", id="tab-history"):
                yield Tree("Commits", id="history-tree")

    def on_mount(self) -> None:
        self._init_git()
        self._populate_branches()
        self._populate_history()

    def _init_git(self) -> None:
        try:
            from Agent.git_integration import get_git_manager
            self._gm = get_git_manager()
            if not self._gm.available:
                self._gm = None
        except Exception:
            self._gm = None

    def _populate_branches(self) -> None:
        container = self.query_one("#branches-content", VerticalScroll)
        if not self._gm:
            container.mount(Label("  Git not available"))
            return

        current = self._gm.current_branch()
        container.mount(Label(
            f"  ⎇ Current: {current}",
        ))

        with self.app.batch_update():
            branches = self._list_branches()
            self._branch_order: List[str] = list(branches[:20])
            for i, b in enumerate(self._branch_order):
                icon = "● " if b == current else "○ "
                btn = Button(
                    f" {icon}{b}",
                    id=f"branch-{i}",
                    classes="branch-item",
                )
                btn._branch_name = b  # noqa: SLF001
                container.mount(btn)

            container.mount(Horizontal(
                Button("+ New", id="btn-branch-new", variant="default"),
                Button("Fetch", id="btn-fetch", variant="default"),
                Button("Pull", id="btn-pull", variant="default"),
                Button("Push", id="btn-push", variant="default"),
                id="branch-actions",
            ))

            status = self._gm.status_summary()
            changed_raw = (
                status.get("changed", [])
                + status.get("staged", [])
                + status.get("untracked", [])
            )
            changed: List[str] = []
            seen: Set[str] = set()
            for f in changed_raw:
                if f not in seen:
                    seen.add(f)
                    changed.append(f)
            if changed:
                container.mount(Static("── Git Staging ──", classes="staging-header"))
                # IDs must be unique: paths like ".lorne/x" and ".lorne_x" collide if we only
                # replace "/" and "." → use index (path is on _file_path for handlers).
                for i, f in enumerate(changed):
                    cat = "M"
                    if f in status.get("untracked", []):
                        cat = "?"
                    elif f in status.get("staged", []):
                        cat = "S"
                        self._staged_files.add(f)

                    # Semantic palette: modified → accent, added/new → green, staged/complete → green, untracked → red.
                    _accent = "#8B5CF6"
                    try:
                        from Interface.ui_prefs import load_prefs
                        from Interface.themes import get_theme
                        _prefs = load_prefs()
                        _accent = str(
                            _prefs.get("accent_color")
                            or get_theme(str(_prefs.get("theme", "Purple Dark"))).get("accent")
                            or _accent,
                        )
                    except Exception:
                        pass
                    color = {"M": _accent, "?": "#EF4444", "S": "#10B981"}.get(cat, "#6B7280")
                    is_selected = (cat == "S")
                    marker = "✓" if is_selected else "○"
                    cb = Checkbox(
                        f"{marker} [{cat}] {f}",
                        value=is_selected,
                        id=f"stage-file-{i}",
                        classes="stage-checkbox",
                    )
                    cb._file_path = f
                    cb._cat = cat
                    container.mount(cb)

                container.mount(Input(
                    placeholder="Commit message…",
                    id="commit-input",
                ))
                container.mount(Button("📦 Commit Selected", id="commit-btn"))

    def _list_branches(self) -> List[str]:
        if not self._gm or not self._gm.repo:
            return []
        try:
            return [b.name for b in self._gm.repo.branches]
        except Exception:
            return []

    def _populate_history(self) -> None:
        tree = self.query_one("#history-tree", Tree)
        tree.root.expand()
        if not self._gm:
            tree.root.add_leaf("Git not available")
            return

        try:
            commits = self._gm.log(limit=30)
            for c in commits:
                short_hash = c.get("hash", "")[:7]
                msg = c.get("message", "")[:50]
                author = c.get("author", "")
                date = c.get("date", "")[:10]

                _accent = "#8B5CF6"
                try:
                    from Interface.ui_prefs import load_prefs
                    from Interface.themes import get_theme
                    _prefs = load_prefs()
                    _accent = str(
                        _prefs.get("accent_color")
                        or get_theme(str(_prefs.get("theme", "Purple Dark"))).get("accent")
                        or _accent,
                    )
                except Exception:
                    pass
                label = Text()
                label.append(f"{short_hash} ", style=f"bold {_accent}")
                label.append(f"{msg} ", style="#E5E7EB")
                label.append(f"({author}, {date})", style="#6B7280")

                node = tree.root.add_leaf(label)
                node.data = c
        except Exception as e:
            tree.root.add_leaf(f"Error: {e}")

    @on(Checkbox.Changed)
    def on_stage_toggle(self, event: Checkbox.Changed) -> None:
        cb = event.checkbox
        file_path = getattr(cb, "_file_path", None)
        cat = getattr(cb, "_cat", "M")
        if not file_path:
            return
        if event.value:
            self._staged_files.add(file_path)
            if self._gm and self._gm.repo:
                try:
                    self._gm.repo.index.add([file_path])
                except Exception:
                    pass
            try:
                cb.label = f"✓ [{cat}] {file_path}"
            except Exception:
                pass
        else:
            self._staged_files.discard(file_path)
            if self._gm and self._gm.repo:
                try:
                    self._gm.repo.git.reset("HEAD", "--", file_path)
                except Exception:
                    pass
            try:
                cb.label = f"○ [{cat}] {file_path}"
            except Exception:
                pass

    @on(Button.Pressed)
    def on_button(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id.startswith("branch-") and btn_id[7:].isdigit():
            idx = int(btn_id[7:])
            names = getattr(self, "_branch_order", [])
            if 0 <= idx < len(names):
                self._switch_branch(names[idx])
            return

        if btn_id == "btn-branch-new":
            self._create_branch()
            return

        if btn_id == "btn-fetch":
            self._do_fetch()
            return

        if btn_id == "btn-pull":
            self._do_pull()
            return

        if btn_id == "btn-push":
            self._do_push()
            return

        if btn_id == "commit-btn":
            self._do_commit()
            return

    def _do_commit(self) -> None:
        if not self._gm or not self._gm.repo:
            self.notify("Git not available", severity="warning")
            return
        try:
            inp = self.query_one("#commit-input", Input)
            msg = inp.value.strip()
            if not msg:
                self.notify("Enter a commit message", severity="warning")
                return
            if not self._staged_files:
                self.notify("Select files to commit", severity="warning")
                return

            repo = self._gm.repo
            for f in self._staged_files:
                try:
                    repo.index.add([f])
                except Exception:
                    pass

            repo.index.commit(msg)
            inp.value = ""
            self._staged_files.clear()
            self.notify(f"Committed: {msg[:40]}")
            self._refresh()
        except Exception as e:
            self.notify(f"Commit error: {e}", severity="error")

    def _switch_branch(self, name: str) -> None:
        if not self._gm or not self._gm.repo:
            return
        try:
            self._gm.repo.git.checkout(name)
            self.notify(f"Switched to: {name}")
            self.post_message(BranchSwitched(name))
            self._refresh()
        except Exception as e:
            self.notify(f"Checkout error: {e}", severity="error")

    def _create_branch(self) -> None:
        from Interface.panels.file_explorer import _InputDialog

        def _do(name: str) -> None:
            if not name or not self._gm or not self._gm.repo:
                return
            try:
                self._gm.repo.git.checkout("-b", name)
                self.notify(f"Created and switched to: {name}")
                self.post_message(BranchSwitched(name))
                self._refresh()
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")

        self.app.push_screen(_InputDialog("New branch name:", _do))

    def _do_fetch(self) -> None:
        if not self._gm or not self._gm.repo:
            self.notify("Git not available", severity="warning")
            return
        try:
            self._gm.repo.git.fetch("--all")
            self.notify("Fetch complete")
            self._refresh()
        except Exception as e:
            self.notify(f"Fetch error: {e}", severity="error")

    def _do_pull(self) -> None:
        if not self._gm or not self._gm.repo:
            self.notify("Git not available", severity="warning")
            return
        try:
            self._gm.repo.git.pull()
            self.notify("Pull complete")
            self._refresh()
        except Exception as e:
            self.notify(f"Pull error: {e}", severity="error")

    def _do_push(self) -> None:
        if not self._gm or not self._gm.repo:
            self.notify("Git not available", severity="warning")
            return
        try:
            self._gm.repo.git.push()
            self.notify("Push complete")
        except Exception as e:
            self.notify(f"Push error: {e}", severity="error")

    def _refresh(self) -> None:
        container = self.query_one("#branches-content", VerticalScroll)
        container.remove_children()
        self._staged_files.clear()
        self._populate_branches()

        tree = self.query_one("#history-tree", Tree)
        tree.root.remove_children()
        self._populate_history()
