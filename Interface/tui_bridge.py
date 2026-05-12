"""Bridge between Agent loop and TUI panels.

Provides thread-safe callbacks that the agent graph nodes call
to stream data into the Textual UI panels. All methods use
app.call_from_thread() for thread safety.
"""
from __future__ import annotations

import sys
import time
import threading
from typing import Any, Dict, List, Optional

_bridge: Optional["TUIBridge"] = None


def get_bridge() -> Optional["TUIBridge"]:
    return _bridge


def set_bridge(bridge: Optional["TUIBridge"]) -> None:
    global _bridge
    _bridge = bridge


class TUIBridge:
    """Adapter between the agent execution loop and TUI panels."""

    def __init__(self, app: Any):
        self.app = app
        self._active = True
        self._stop_event = threading.Event()
        self._last_file_refresh = 0.0
        self._confirm_event: Optional[threading.Event] = None
        self._confirm_result: bool = False
        self._input_event: Optional[threading.Event] = None
        self._input_result: str = ""

    def _call(self, fn, *args, **kwargs):
        if not self._active:
            return
        try:
            self.app.call_from_thread(fn, *args, **kwargs)
        except Exception as e:
            try:
                print(f"[TUI Bridge error] {e}", file=sys.stderr)
            except Exception:
                pass

    # ─── Stop mechanism ───────────────────────────────

    def request_stop(self) -> None:
        self._stop_event.set()

    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def clear_stop(self) -> None:
        self._stop_event.clear()

    # ─── Chat panel (primary output) ─────────────────

    def on_thought(self, text: str) -> None:
        self._call(self.app.chat.add_thought, text)

    def on_action(self, tool_name: str, args_summary: str = "") -> None:
        self._call(self.app.chat.add_tool_message, tool_name, args_summary)

    def on_info(self, text: str) -> None:
        self._call(self.app.chat.add_info, text)

    def on_warning(self, text: str) -> None:
        self._call(self.app.chat.add_warning, text)

    def on_error(self, text: str) -> None:
        self._call(self.app.chat.add_error, text)

    def on_success(self, text: str) -> None:
        self._call(self.app.chat.add_success, text)

    def on_model_reply(self, text: str, usage: Optional[Dict[str, Any]] = None) -> None:
        self._call(self.app.chat.add_assistant_message, text, usage)

    def on_chat_user_message(self, text: str, turn_index: int) -> None:
        """Сообщение пользователя с индексом хода (кнопка отката)."""
        self._call(self.app.chat.add_user_message, text, turn_index)

    def on_chat_reload_messages(self, messages: List[Any]) -> None:
        """Перерисовка чата после отката или смены сессии.

        Нельзя использовать call_from_thread из потока приложения — Textual выбрасывает
        RuntimeError. call_later безопасен и с UI-потока (после выбора сессии), и с воркера.
        """
        try:
            self.app.call_later(self.app.chat.rebuild_from_langchain_messages, messages)
        except Exception as e:
            try:
                print(f"[TUI Bridge reload error] {e}", file=sys.stderr)
            except Exception:
                pass

    def on_separator(self, label: str = "") -> None:
        self._call(self.app.chat.add_separator, label)

    # ─── File / code visualization ────────────────────

    def on_file_working(self, path: str) -> None:
        self._call(self.app.chat.add_file_indicator, path)

    def on_code(self, code: str, language: str = "python",
                filepath: str = "") -> None:
        self._call(self.app.chat.add_code_block, code, language, filepath)

    def on_diff(self, old_text: str, new_text: str,
                filepath: str = "") -> None:
        old_lines = len(old_text.splitlines()) if old_text else 0
        new_lines = len(new_text.splitlines()) if new_text else 0
        delta = new_lines - old_lines
        sign = "+" if delta >= 0 else ""
        summary = f"{filepath}: {old_lines} → {new_lines} lines ({sign}{delta})"
        self._call(self.app.chat.add_info, f"📝 {summary}")

    def on_tool_result(self, tool_name: str, result: Any) -> None:
        # Карточки для почти всех тулов; мутации файлов — короткая строка + diff
        # (см. accumulate_tool_result / CodeDiffBlock).
        try:
            from Interface.panels.ai_chat._constants import _WRITE_TOOLS as _WT
        except Exception:
            _WT = frozenset()

        if tool_name == "plan_tool":
            self._call(self.app.chat.add_plan_tool_card, result)
        elif tool_name in _WT:
            summary = ""
            if isinstance(result, dict):
                if result.get("error"):
                    summary = f"error: {result.get('error')}"
                elif result.get("action"):
                    summary = str(result.get("action", ""))
                elif result.get("file_path"):
                    summary = str(result.get("file_path", ""))
                elif result.get("path"):
                    summary = str(result.get("path", ""))
                elif result.get("stdout"):
                    summary = str(result["stdout"])[:100]
            elif isinstance(result, str):
                summary = result[:80]
            self._call(self.app.chat.add_tool_result, tool_name, summary)
        else:
            self._call(self.app.chat.add_tool_card, tool_name, result)

        if isinstance(result, dict):
            self._call(self.app.chat.accumulate_tool_result, tool_name, result)
            self._call(self.app.chat.accumulate_web_tool_result, tool_name, result)

    def on_code_separator(self) -> None:
        pass

    # ─── File explorer ───────────────────────────────

    def on_file_changed(self, path: str = "") -> None:
        now = time.time()
        if now - self._last_file_refresh < 1.5:
            return
        self._last_file_refresh = now
        self._call(self.app.file_explorer.refresh_tree)

    # ─── Context ─────────────────────────────────────

    def on_context_update(self, used: int, total: int) -> None:
        self._call(self.app.chat.update_context, used, total)

    # ─── Status bar ──────────────────────────────────

    def on_status_update(self, model: str = "", branch: str = "",
                         tokens: str = "", rag: str = "") -> None:
        self._call(self.app.update_status, model, branch, tokens, rag)

    # ─── Plan (displayed in chat) ────────────────────

    def on_plan_set(self, steps: list) -> None:
        self._call(self.app.chat.add_info, f"📋 Plan: {len(steps)} steps")
        for i, s in enumerate(steps):
            text = s.get("step", s) if isinstance(s, dict) else str(s)
            self._call(self.app.chat.add_info, f"  {i+1}. {text}")

    def on_plan_update(self, step_index: int, status: str,
                       note: str = "") -> None:
        icons = {"completed": "✓", "in_progress": "▶", "error": "✗"}
        icon = icons.get(status, "○")
        self._call(self.app.chat.add_info, f"  {icon} Step {step_index}: {status}")

    def on_plan_clear(self) -> None:
        self._call(self.app.chat.add_info, "Plan cleared")

    # ─── Creator mode ────────────────────────────────

    def on_creator_tree(self, tree_data: dict) -> None:
        self._call(self.app.active_agents.update_creator_tree, tree_data)

    def on_creator_worker_update(self, worker_id: str, tool_name: str = "",
                                  action: str = "", thinking: str = "") -> None:
        self._call(self.app.chat.update_creator_worker, worker_id, tool_name, action, thinking)

    def on_creator_progress_start(self, task: str = "", total_workers: int = 0) -> None:
        """Mount the animated progress block in the main chat."""
        self._call(self.app.chat.start_creator_progress, task, total_workers)

    def on_creator_progress_update(
        self,
        phase: str = "",
        percent: float = 0.0,
        completed: int = 0,
        total: int = 0,
    ) -> None:
        """Push a new target percent / phase label to the progress block."""
        self._call(
            self.app.chat.update_creator_progress,
            phase, percent, completed, total,
        )

    def on_creator_progress_finish(self, summary: str = "") -> None:
        """Mark the progress block as complete (fills to 100 %)."""
        self._call(self.app.chat.finish_creator_progress, summary)

    def on_creator_hide(self) -> None:
        pass

    # ─── Deep Solver ─────────────────────────────────

    def on_deep_checkpoint(self, cp_id: str, index: int, title: str,
                           summary: str = "", turn_index: int = 0) -> None:
        """Mount a ``DeepCheckpointBlock`` card in the main chat stream."""
        self._call(
            self.app.chat.add_deep_checkpoint,
            cp_id, index, title, summary, turn_index,
        )

    def on_deep_context_chip(self, cp_id: str, label: str) -> None:
        """Show a pseudo-attachment chip for a continued checkpoint."""
        self._call(self.app.chat.add_deep_context_chip, cp_id, label)

    def on_deep_status(
        self, *, running: bool, elapsed: str = "",
        checkpoints: int = 0, model: str = "", current_step: int = 0,
    ) -> None:
        """Refresh the elapsed-time badge rendered above the chat input
        while a Deep Solver run is live. Called on a heartbeat from the
        Deep loop so the user can watch wall-clock time tick up without
        staring into the main message stream.
        """
        self._call(
            self.app.chat.set_deep_status,
            running=running, elapsed=elapsed,
            checkpoints=checkpoints, model=model,
            current_step=current_step,
        )

    def on_download_progress(self, *, download_id: str, url: str,
                             received_bytes: int, total_bytes: int,
                             elapsed: float, done: bool = False,
                             error: str = "") -> None:
        """Push a download-progress tick to the chat UI. The chat panel
        lazily creates / updates a :class:`DownloadProgressBlock` with
        percentage, size, throughput and a cancel button.
        """
        self._call(
            self.app.chat.update_download_progress,
            download_id=download_id, url=url,
            received_bytes=int(received_bytes),
            total_bytes=int(total_bytes),
            elapsed=float(elapsed), done=bool(done), error=str(error or ""),
        )

    # ─── Agent working state ─────────────────────────

    def on_agent_start(self) -> None:
        self._call(self.app.chat.show_stop_button)

    def on_agent_done(self) -> None:
        self._call(self.app.chat.hide_stop_button)

    # ─── TUI-aware tool interaction ──────────────────

    def request_confirmation(self, prompt: str, detail: str = "") -> bool:
        """Show a confirmation dialog in TUI and block until user responds."""
        self._confirm_event = threading.Event()
        self._confirm_result = False

        def _show():
            from Interface.panels.file_explorer import _ConfirmDialog
            def _on_result(confirmed: bool):
                self._confirm_result = confirmed
                if self._confirm_event:
                    self._confirm_event.set()
            self.app.push_screen(_ConfirmDialog(prompt, detail, _on_result))

        self._call(_show)
        if self._confirm_event:
            self._confirm_event.wait(timeout=120)
        return self._confirm_result

    def request_input(self, prompt: str) -> str:
        """Show an input dialog in TUI and block until user responds."""
        self._input_event = threading.Event()
        self._input_result = ""

        def _show():
            from Interface.panels.file_explorer import _InputDialog
            def _on_input(value: str):
                self._input_result = value
                if self._input_event:
                    self._input_event.set()
            self.app.push_screen(_InputDialog(prompt, _on_input))

        self._call(_show)
        if self._input_event:
            self._input_event.wait(timeout=120)
        return self._input_result

    def request_user_choice(self, question: str) -> str:
        """Yes/No (+ optional custom text) for ask_user; blocks until answered."""
        self._input_event = threading.Event()
        self._input_result = ""

        def _show():
            from Interface.panels.file_explorer import _AskUserDialog
            def _on_choice(value: str):
                self._input_result = value
                if self._input_event:
                    self._input_event.set()
            self.app.push_screen(_AskUserDialog(question, _on_choice))

        self._call(_show)
        if self._input_event:
            self._input_event.wait(timeout=600)
        return self._input_result

    # ─── Lifecycle ───────────────────────────────────

    def stop(self) -> None:
        self._active = False
