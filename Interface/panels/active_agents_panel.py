"""Lower-left panel — live agent / worker tree (Creator mode)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from rich.text import Text

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static, Tree

PURPLE = "#8B5CF6"
GRAY = "#6B7280"
GREEN = "#10B981"
RED = "#EF4444"
YELLOW = "#F59E0B"
DIM = "#4B5563"
ORANGE = "#F97316"


class AgentWorkerSelected(Message):
    """User selected a worker in the tree (open dedicated activity view)."""

    def __init__(self, worker_id: str) -> None:
        super().__init__()
        self.worker_id = worker_id


class AgentMainChatSelected(Message):
    """User wants the main project chat again."""

    pass


class ActiveAgentsPanel(Vertical):
    """Shows running agents / workers; click to open that worker's stream in chat."""

    DEFAULT_CSS = """
    ActiveAgentsPanel {
        height: 1fr;
        min-height: 6;
        border-top: solid #2D2D3D;
        background: #0D0D0D;
    }
    #agents-panel-title {
        dock: top;
        height: 1;
        background: #1a1a2e;
        color: #A78BFA;
        text-style: bold;
        padding: 0 1;
    }
    #agents-tree {
        height: 1fr;
        background: #0D0D0D;
        padding: 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent_data: dict = {}

    def compose(self) -> ComposeResult:
        yield Static(" Агенты", id="agents-panel-title")
        yield Tree("Root", id="agents-tree")

    def on_mount(self) -> None:
        try:
            tree = self.query_one("#agents-tree", Tree)
            tree.root.expand()
            tree.root.set_label(Text("Сейчас", style=f"bold {PURPLE}"))
            tree.root.add(
                Text("💬 Общий чат", style=f"bold {GREEN}"),
                data={"worker_id": "", "main_chat": True},
            )
            tree.root.add_leaf(Text("Нет активных воркеров", style=DIM))
        except Exception:
            pass

    def _accent(self) -> str:
        try:
            from Interface.ui_prefs import load_prefs
            from Interface.themes import get_theme
            prefs = load_prefs()
            theme = get_theme(str(prefs.get("theme", "Purple Dark")))
            return str(prefs.get("accent_color") or theme.get("accent") or PURPLE)
        except Exception:
            return PURPLE

    def update_creator_tree(self, tree_data: dict) -> None:
        try:
            self._agent_data = tree_data
            tree = self.query_one("#agents-tree", Tree)
            tree.root.remove_children()
            tree.root.set_label(Text("Сейчас", style=f"bold {self._accent()}"))
            tree.root.add(
                Text("💬 Общий чат", style=f"bold {GREEN}"),
                data={"worker_id": "", "main_chat": True},
            )
            self._build_tree_node(tree.root, tree_data)
            tree.root.expand_all()
        except Exception:
            pass

    def _build_tree_node(self, parent, data: dict) -> None:
        if not isinstance(data, dict):
            return
        wid = data.get("worker_id", "agent")
        task = str(data.get("task", ""))[:48]
        status = data.get("status", "working")
        model = data.get("model_type", "")

        status_icons = {
            "done": "●", "working": "◐", "error": "✗",
            "pending": "○", "stopped": "◑",
        }
        status_colors = {
            "done": GREEN, "working": YELLOW, "error": RED,
            "pending": GRAY, "stopped": ORANGE,
        }
        icon = status_icons.get(status, "○")
        color = status_colors.get(status, GRAY)

        label = Text()
        label.append(f"{icon} ", style="default")
        label.append(f"{wid}", style=f"bold {color}")
        if task:
            label.append(f"  {task}", style="#E5E7EB")
        if model:
            label.append(f"  [{model}]", style=DIM)

        node = parent.add(label, data={"worker_id": wid, "status": status})
        for child in data.get("children", []):
            self._build_tree_node(node, child)

    @on(Tree.NodeSelected, "#agents-tree")
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        node_data = event.node.data
        if not node_data or not isinstance(node_data, dict):
            return
        if node_data.get("main_chat"):
            self.post_message(AgentMainChatSelected())
            return
        worker_id = node_data.get("worker_id")
        if worker_id is None:
            return
        ws = str(worker_id).strip()
        if not ws:
            self.post_message(AgentMainChatSelected())
            return
        self.post_message(AgentWorkerSelected(ws))
