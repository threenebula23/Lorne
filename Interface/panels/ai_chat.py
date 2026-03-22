"""AI Chat panel — messages, input, model/mode selector, agents tab, settings."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rich.markup import escape
from rich.text import Text

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, Input, Label, RichLog, Select, Static,
    TabbedContent, TabPane, TextArea, Tree,
)
from textual.message import Message


class ChatSubmitted(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class ModelChanged(Message):
    def __init__(self, model_id: str) -> None:
        super().__init__()
        self.model_id = model_id


class ModeToggled(Message):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode


class StopRequested(Message):
    pass


PURPLE = "#8B5CF6"
PURPLE_LIGHT = "#A78BFA"
GRAY = "#6B7280"
GREEN = "#10B981"
RED = "#EF4444"
YELLOW = "#F59E0B"
DIM = "#4B5563"
BLUE = "#3B82F6"
CYAN = "#06B6D4"
ORANGE = "#F97316"

MODES = ["Normal", "Creator", "Agent", "Research"]


class AIChatPanel(Vertical):
    """Right panel — AI conversation + controls + agents tab."""

    def __init__(self, models: Optional[List[Dict]] = None,
                 current_model: str = "", **kwargs):
        super().__init__(**kwargs)
        self._models = models or []
        self._current_model = current_model
        self._current_mode = "Normal"
        self._context_used = 0
        self._context_total = 128_000
        self._agent_data: dict = {}
        self._selected_worker: Optional[str] = None
        self._worker_logs: Dict[str, List[str]] = {}
        self._context_hints: List[str] = []

    def compose(self) -> ComposeResult:
        with TabbedContent("💬 Chat", "🤖 Agents", "⚙️ Settings"):
            with TabPane("💬 Chat", id="tab-chat"):
                yield RichLog(id="chat-messages", wrap=True, markup=True)
                yield Vertical(id="chat-input-area")
            with TabPane("🤖 Agents", id="tab-agents"):
                yield Static("Agent Hierarchy", id="agents-header")
                yield Tree("Root", id="creator-tree")
                yield Static("── Agent Details ──", id="agent-detail-header")
                yield RichLog(id="agent-detail-log", wrap=True, markup=True)
            with TabPane("⚙️ Settings", id="tab-ai-settings"):
                yield VerticalScroll(id="ai-settings")

    def on_mount(self) -> None:
        self._build_input_area()
        self._build_settings()
        self._add_welcome()
        try:
            tree = self.query_one("#creator-tree", Tree)
            tree.root.expand()
            tree.root.set_label(Text("🌐 Agent Pool", style=f"bold {PURPLE}"))
            tree.root.add_leaf(Text("No agents running", style=DIM))
        except Exception:
            pass

    def _build_input_area(self) -> None:
        area = self.query_one("#chat-input-area", Vertical)
        area.mount(Input(
            placeholder="Message… (Enter to send)",
            id="chat-input",
        ))

        model_options = []
        for m in self._models:
            name = m.get("name", m.get("id", "?"))
            mid = m.get("id", name)
            short_name = name
            if "/" in short_name:
                short_name = short_name.split("/")[-1]
            if len(short_name) > 25:
                short_name = short_name[:22] + "…"
            model_options.append((short_name, mid))
        if not model_options:
            model_options = [("Default", "default")]

        mode_options = [(m, m.lower()) for m in MODES]

        area.mount(Horizontal(
            Select(model_options, value=self._current_model or "default",
                   id="model-select", allow_blank=False),
            Select(mode_options, value="normal", id="mode-select", allow_blank=False),
            Label("0%", id="ctx-label"),
            Button("⏹ Stop", id="stop-btn"),
            Button("📤", id="send-btn", variant="primary"),
            id="chat-controls",
        ))

    def _build_settings(self) -> None:
        settings = self.query_one("#ai-settings", VerticalScroll)

        settings.mount(Label("── 🔑 API ──"))
        settings.mount(Label("OpenRouter API Key"))
        current_key = os.environ.get("OPENROUTER_API_KEY", "")
        masked = current_key[:8] + "…" if len(current_key) > 8 else current_key
        settings.mount(Input(
            value=masked, placeholder="sk-or-…",
            password=True, id="api-key-input",
        ))
        settings.mount(Button("Save API Key", id="save-api-key"))

        settings.mount(Label("── 🖥️ Local Model ──"))
        settings.mount(Label("Local Model IP / URL"))
        local_url = os.environ.get("LOCAL_MODEL_URL", "http://localhost:1234/v1")
        settings.mount(Input(
            value=local_url, placeholder="http://localhost:1234/v1",
            id="local-model-url",
        ))
        settings.mount(Button("Save Local URL", id="save-local-url"))

        settings.mount(Label("── 💰 Balance ──"))
        settings.mount(Button("Check Balance", id="check-balance"))
        settings.mount(Static("", id="balance-display"))

        settings.mount(Label("── 🤖 Custom Model ──"))
        settings.mount(Input(
            placeholder="e.g. openai/gpt-4o",
            id="custom-model-input",
        ))
        settings.mount(Button("Add Model", id="add-model-btn"))

        settings.mount(Label("── 📊 Profile ──"))
        settings.mount(Select(
            [("Fast", "fast"), ("Balanced", "balanced"), ("Quality", "quality")],
            value="balanced", id="profile-select",
        ))
        settings.mount(Static(
            "[dim]Theme, density, syntax, hotkeys →\nSettings tab in File Explorer (left panel)[/]",
            id="settings-hint",
        ))

    def _add_welcome(self) -> None:
        log = self.query_one("#chat-messages", RichLog)
        log.write(Text("TCA — Terminal Coding Assistant", style=f"bold {PURPLE}"))
        log.write(Text("Type a message or use /help for commands", style=DIM))
        log.write(Text("Right-click (Ctrl+Click on Mac) for context menus", style=DIM))
        log.write(Text("─" * 30, style=DIM))

    # ─── Public API ────────────────────────────────

    def add_user_message(self, text: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        msg = Text()
        msg.append("You: ", style=f"bold {PURPLE_LIGHT}")
        msg.append(text, style="#E5E7EB")
        log.write(msg)

    def add_assistant_message(self, text: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        log.write(Text(""))
        header = Text()
        header.append("🤖 AI: ", style=f"bold {GREEN}")
        log.write(header)
        for line in text[:4000].split("\n"):
            if line.startswith("```"):
                log.write(Text(line, style=CYAN))
            elif line.startswith("#"):
                log.write(Text(line, style=f"bold {PURPLE_LIGHT}"))
            elif line.startswith("- ") or line.startswith("* "):
                log.write(Text(f"  {line}", style="#E5E7EB"))
            else:
                log.write(Text(line, style="#E5E7EB"))
        log.write(Text(""))

    def add_tool_message(self, tool_name: str, summary: str = "") -> None:
        log = self.query_one("#chat-messages", RichLog)
        msg = Text()
        msg.append(f"  ⚡ {tool_name}", style=f"bold {PURPLE}")
        if summary:
            msg.append(f"  {summary[:120]}", style=GRAY)
        log.write(msg)

    def add_tool_result(self, tool_name: str, summary: str = "") -> None:
        log = self.query_one("#chat-messages", RichLog)
        msg = Text()
        msg.append(f"  ← {tool_name}", style=f"{DIM}")
        if summary:
            msg.append(f"  {summary[:120]}", style=DIM)
        log.write(msg)

    def add_thought(self, text: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        for line in (text or "")[:2000].split("\n")[:40]:
            log.write(Text(f"  💭 {line}", style=f"italic {DIM}"))

    def add_error(self, text: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        log.write(Text(f"  ✗ {text}", style=f"bold {RED}"))

    def add_info(self, text: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        log.write(Text(f"  {text}", style=GRAY))

    def register_context_hint(self, path: Path) -> None:
        """Remember a file path for the user (does not start the agent)."""
        try:
            p = str(path.resolve())
        except Exception:
            p = str(path)
        if p not in self._context_hints:
            self._context_hints.append(p)
        log = self.query_one("#chat-messages", RichLog)
        log.write(Text(""))
        log.write(Text("  📎 Контекст (подсказка для следующих сообщений):", style=f"bold {CYAN}"))
        log.write(Text(f"     {p}", style="#E5E7EB"))
        log.write(Text(
            "     Агент не запущен — при необходимости ищи код в этом файле.",
            style=DIM,
        ))

    def get_context_hints(self) -> List[str]:
        """Paths the user marked via «Add to context»."""
        return list(self._context_hints)

    def add_success(self, text: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        log.write(Text(f"  ✓ {text}", style=f"bold {GREEN}"))

    def add_warning(self, text: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        log.write(Text(f"  ⚠ {text}", style=f"bold {YELLOW}"))

    def add_separator(self, label: str = "") -> None:
        log = self.query_one("#chat-messages", RichLog)
        sep = Text()
        sep.append("─" * 15, style=DIM)
        if label:
            sep.append(f" {label} ", style=GRAY)
            sep.append("─" * 15, style=DIM)
        log.write(sep)

    def add_file_indicator(self, path: str) -> None:
        log = self.query_one("#chat-messages", RichLog)
        name = Path(path).name if path else "unknown"
        log.write(Text(f"  📄 {name}", style=f"{BLUE}"))

    def add_code_block(self, code: str, language: str = "python", filepath: str = "") -> None:
        log = self.query_one("#chat-messages", RichLog)
        label = filepath if filepath else language
        log.write(Text(f"  ┌─ {label} ─", style=CYAN))
        for line in code[:1500].split("\n")[:20]:
            log.write(Text(f"  │ {line}", style="#D1D5DB"))
        remaining = len(code.split("\n")) - 20
        if remaining > 0:
            log.write(Text(f"  │ ... ({remaining} more lines)", style=DIM))
        log.write(Text(f"  └─", style=CYAN))

    def update_context(self, used: int, total: int) -> None:
        self._context_used = used
        self._context_total = total
        pct = round(100 * used / total) if total > 0 else 0
        try:
            lbl = self.query_one("#ctx-label", Label)
            if pct < 50:
                color = GREEN
            elif pct < 80:
                color = YELLOW
            else:
                color = RED
            lbl.update(Text(f"{pct}%", style=f"bold {color}"))
        except Exception:
            pass

    def update_model(self, model_id: str) -> None:
        self._current_model = model_id
        try:
            sel = self.query_one("#model-select", Select)
            sel.value = model_id
        except Exception:
            pass

    # ─── Stop button ────────────────────────────────

    def show_stop_button(self) -> None:
        try:
            btn = self.query_one("#stop-btn", Button)
            btn.add_class("visible")
        except Exception:
            pass

    def hide_stop_button(self) -> None:
        try:
            btn = self.query_one("#stop-btn", Button)
            btn.remove_class("visible")
        except Exception:
            pass

    # ─── Creator mode tree with colored circles ─────

    def update_creator_tree(self, tree_data: dict) -> None:
        try:
            self._agent_data = tree_data
            tree = self.query_one("#creator-tree", Tree)
            tree.root.remove_children()
            tree.root.set_label(Text("🌐 Agent Pool", style=f"bold {PURPLE}"))
            self._build_tree_node(tree.root, tree_data)
            tree.root.expand_all()
        except Exception:
            pass

    def _build_tree_node(self, parent, data: dict) -> None:
        if not isinstance(data, dict):
            return
        wid = data.get("worker_id", "agent")
        task = str(data.get("task", ""))[:40]
        status = data.get("status", "working")
        model = data.get("model_type", "")

        status_icons = {
            "done": "🟢", "working": "🟡", "error": "🔴",
            "pending": "⚪", "stopped": "🟠",
        }
        status_colors = {
            "done": GREEN, "working": YELLOW, "error": RED,
            "pending": GRAY, "stopped": ORANGE,
        }
        icon = status_icons.get(status, "⚪")
        color = status_colors.get(status, GRAY)

        label = Text()
        label.append(f"{icon} ", style="default")
        label.append(f"{wid}", style=f"bold {color}")
        if task:
            label.append(f": {task}", style="#E5E7EB")
        if model:
            label.append(f" [{model}]", style=DIM)
        label.append(f"  ({status})", style=color)

        node = parent.add(label, data={"worker_id": wid, "status": status})
        for child in data.get("children", []):
            self._build_tree_node(node, child)

    @on(Tree.NodeSelected, "#creator-tree")
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        node_data = event.node.data
        if not node_data or not isinstance(node_data, dict):
            return
        worker_id = node_data.get("worker_id")
        if not worker_id:
            return
        self._selected_worker = worker_id
        self._refresh_agent_detail()

    def _refresh_agent_detail(self) -> None:
        if not self._selected_worker:
            return
        try:
            log = self.query_one("#agent-detail-log", RichLog)
            header = self.query_one("#agent-detail-header", Static)
            header.update(Text(f"── {self._selected_worker} ──", style=f"bold {PURPLE}"))
            log.clear()
            logs = self._worker_logs.get(self._selected_worker, [])
            if logs:
                for entry in logs[-30:]:
                    log.write(Text(entry, style="#E5E7EB"))
            else:
                log.write(Text("No activity yet — select an agent from the tree", style=DIM))
        except Exception:
            pass

    def update_creator_worker(self, worker_id: str, tool_name: str = "",
                               action: str = "", thinking: str = "") -> None:
        if worker_id not in self._worker_logs:
            self._worker_logs[worker_id] = []

        entries = self._worker_logs[worker_id]
        if tool_name:
            entries.append(f"⚡ {tool_name}: {action[:100]}")
        if thinking:
            entries.append(f"💭 {thinking[:200]}")

        if len(entries) > 100:
            self._worker_logs[worker_id] = entries[-50:]

        try:
            log = self.query_one("#agent-detail-log", RichLog)
            if self._selected_worker == worker_id:
                msg = Text()
                msg.append(f"[{worker_id}] ", style=f"bold {PURPLE}")
                if tool_name:
                    msg.append(f"⚡ {tool_name} ", style=f"{CYAN}")
                if action:
                    msg.append(action[:100], style="#E5E7EB")
                log.write(msg)
                if thinking:
                    log.write(Text(f"  💭 {thinking[:200]}", style=f"italic {DIM}"))
        except Exception:
            pass

    # ─── Event handlers ────────────────────────────

    @on(Input.Submitted, "#chat-input")
    def on_chat_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if text:
            self.post_message(ChatSubmitted(text))

    @on(Button.Pressed, "#send-btn")
    def on_send_click(self) -> None:
        try:
            inp = self.query_one("#chat-input", Input)
            text = inp.value.strip()
            inp.value = ""
            if text:
                self.post_message(ChatSubmitted(text))
        except Exception:
            pass

    @on(Button.Pressed, "#stop-btn")
    def on_stop_click(self) -> None:
        self.post_message(StopRequested())

    @on(Select.Changed, "#mode-select")
    def on_mode_change(self, event: Select.Changed) -> None:
        if not event.value or event.value == Select.BLANK:
            return
        mode = str(event.value)
        self._current_mode = mode
        self.post_message(ModeToggled(mode))
        self.notify(f"Mode: {mode}")

    @on(Select.Changed, "#model-select")
    def on_model_change(self, event: Select.Changed) -> None:
        if event.value and event.value != Select.BLANK:
            self.post_message(ModelChanged(str(event.value)))

    @on(Button.Pressed, "#save-api-key")
    def on_save_api_key(self) -> None:
        try:
            inp = self.query_one("#api-key-input", Input)
            key = inp.value.strip()
            if key and not key.endswith("…"):
                os.environ["OPENROUTER_API_KEY"] = key
                env_path = Path.cwd() / ".env"
                _update_env_file(env_path, "OPENROUTER_API_KEY", key)
                self.notify("API key saved")
            else:
                self.notify("Enter a valid API key", severity="warning")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    @on(Button.Pressed, "#save-local-url")
    def on_save_local_url(self) -> None:
        try:
            inp = self.query_one("#local-model-url", Input)
            url = inp.value.strip()
            if url:
                os.environ["LOCAL_MODEL_URL"] = url
                env_path = Path.cwd() / ".env"
                _update_env_file(env_path, "LOCAL_MODEL_URL", url)
                self.notify(f"Local URL saved: {url}")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    @on(Button.Pressed, "#check-balance")
    def on_check_balance(self) -> None:
        display = self.query_one("#balance-display", Static)
        display.update(Text("Checking…", style=YELLOW))

        def _check():
            try:
                from Agent.llm_provider import fetch_openrouter_credits, format_credits_info
                creds = fetch_openrouter_credits()
                if creds:
                    usage = creds.get("usage", 0)
                    limit = creds.get("limit")
                    if limit is not None and limit > 0:
                        remaining = max(0, limit - usage)
                        txt = f"💰 Balance: ${remaining:.4f} (used ${usage:.4f})"
                    else:
                        txt = f"💰 Used: ${usage:.4f}"
                    self.app.call_from_thread(display.update, Text(txt, style=GREEN))
                else:
                    self.app.call_from_thread(display.update, Text("No data", style=RED))
            except Exception as e:
                self.app.call_from_thread(display.update, Text(f"Error: {e}", style=RED))

        threading.Thread(target=_check, daemon=True).start()

    @on(Button.Pressed, "#add-model-btn")
    def on_add_model(self) -> None:
        try:
            inp = self.query_one("#custom-model-input", Input)
            model_id = inp.value.strip()
            if not model_id:
                return
            inp.value = ""
            short = model_id.split("/")[-1] if "/" in model_id else model_id
            if len(short) > 25:
                short = short[:22] + "…"
            self._models.append({"name": short, "id": model_id})
            model_options = []
            for m in self._models:
                name = m.get("name", m.get("id", "?"))
                mid = m.get("id", name)
                sn = name.split("/")[-1] if "/" in name else name
                if len(sn) > 25:
                    sn = sn[:22] + "…"
                model_options.append((sn, mid))
            sel = self.query_one("#model-select", Select)
            sel.set_options(model_options)
            sel.value = model_id
            self.post_message(ModelChanged(model_id))
            self.notify(f"Model added: {model_id}")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")


def _update_env_file(path: Path, key: str, value: str) -> None:
    lines = []
    found = False
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")
