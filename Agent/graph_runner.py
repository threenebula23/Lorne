"""LangGraph agent graph: call_model / execute_tools / workflow compilation."""
import json
import re as _re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, StateGraph, MessagesState
from json_repair import repair_json

from .spinner import LiveSpinner
from .message_utils import (
    sanitize_messages, is_retriable_bind_error, is_transient_error,
    strip_think_tags, normalize_tool_call, reconstruct_broken_content,
    annotate_errors, MAX_LLM_RETRIES,
)

try:
    from Interface.visualization import (
        display_agent_action, display_tool_result, print_warning, print_error, print_thinking,
    )
except ImportError:
    def display_agent_action(sn, name, args): print(f"  Tool: {name}")
    def display_tool_result(sn, name, result): print(f"  Result: {name}")
    def print_warning(m): print(f"  ⚠ {m}")
    def print_error(m): print(f"  ✗ {m}")
    def print_thinking(t=""): print(f"  Thinking: {t}")

try:
    from Interface.tui_bridge import get_bridge
except ImportError:
    def get_bridge(): return None


class AgentGraph:
    """Encapsulates a LangGraph agent+tools workflow with mutable LLM binding.

    Holds a reference to the current llm_with_tools so that call_model can
    rebind on provider errors without rebuilding the entire graph.
    """

    def __init__(self, llm_with_tools, llm_raw, tool_map: Dict[str, Any],
                 model_name: str, is_reasoning: bool = False,
                 bind_tools_fn=None, tools_list=None):
        self.llm_with_tools = llm_with_tools
        self.llm_raw = llm_raw
        self.tool_map = tool_map
        self.model_name = model_name
        self.is_reasoning = is_reasoning
        self.parallel_tools_disabled = False
        self._bind_tools_fn = bind_tools_fn
        self._tools_list = tools_list
        self._app = self._build()

    # ─── LangGraph nodes ────────────────────────────────────────

    def _call_model(self, state: MessagesState) -> Dict[str, List[AIMessage]]:
        messages = sanitize_messages(state["messages"])

        raw_response = None
        last_error = None

        for attempt in range(MAX_LLM_RETRIES + 1):
            spinner = LiveSpinner("Модель думает")
            spinner.start()
            try:
                raw_response = self.llm_with_tools.invoke(messages)
                spinner.stop()
                last_error = None
                break
            except Exception as e:
                spinner.stop()
                last_error = e

                if is_retriable_bind_error(e) and not self.parallel_tools_disabled:
                    print_warning("Провайдер не поддерживает parallel_tool_calls — повторяю без него")
                    self.parallel_tools_disabled = True
                    if self._bind_tools_fn and self._tools_list:
                        self.llm_with_tools = self._bind_tools_fn(
                            self.llm_raw, self.model_name, self._tools_list,
                            force_no_parallel=True,
                        )
                    continue

                if is_transient_error(e) and attempt < MAX_LLM_RETRIES:
                    wait = (attempt + 1) * 3
                    print_warning(
                        f"Ошибка провайдера, повтор через {wait}с… "
                        f"({attempt + 1}/{MAX_LLM_RETRIES})"
                    )
                    time.sleep(wait)
                    continue

                break

        if last_error is not None:
            error_msg = f"Ошибка LLM: {type(last_error).__name__}: {last_error}"
            print_error(error_msg)
            bridge = get_bridge()
            if bridge:
                bridge.on_error(error_msg)
            return {"messages": [AIMessage(content=error_msg)]}

        content = raw_response.content or ""
        meta = getattr(raw_response, "response_metadata", None) or {}
        if isinstance(content, str):
            content = content.encode("utf-8", "ignore").decode("utf-8", "ignore")
            if self.is_reasoning:
                content = strip_think_tags(content)

        thought_match = _re.search(r"<thought>([\s\S]*?)</thought>", content)
        if thought_match:
            thought = thought_match.group(1).strip()
            if thought:
                print_thinking(thought)
                bridge = get_bridge()
                if bridge:
                    bridge.on_thought(thought)

        if getattr(raw_response, "tool_calls", None):
            return {"messages": [AIMessage(
                content=content or "",
                tool_calls=raw_response.tool_calls,
                response_metadata=meta,
            )]}

        fixed_content = repair_json(content)
        if fixed_content.strip():
            try:
                parsed = json.loads(fixed_content)
                parsed_tools = [parsed] if not isinstance(parsed, list) else parsed
                tool_calls = []
                for t in parsed_tools:
                    if not isinstance(t, dict) or "function" not in t:
                        continue
                    func = t["function"]
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    elif not isinstance(args, dict):
                        args = {}
                    tool_calls.append({
                        "name": func["name"],
                        "args": args,
                        "id": str(t.get("id", "call_" + str(hash(func["name"])))),
                        "type": "tool_call",
                    })
                if tool_calls:
                    return {"messages": [AIMessage(
                        content="", tool_calls=tool_calls, response_metadata=meta,
                    )]}
            except json.JSONDecodeError:
                pass

        return {"messages": [AIMessage(content=content, response_metadata=meta)]}

    _READ_ONLY_TOOLS = frozenset({
        "read_file", "list_files", "search_in_files", "rag_search",
        "get_file_line_count", "load_plan", "git_log", "git_diff", "git_status",
    })

    _FILE_TOOLS = frozenset({
        "read_file", "edit_file", "write_file", "create_code_file",
        "append_code_snippet",
    })

    def _run_single_tool(self, idx: int, tc_norm: dict) -> ToolMessage:
        """Execute a single tool call and return a ToolMessage."""
        tool_name = str(tc_norm.get("name") or "")
        tool_args = tc_norm.get("args") or {}
        tool_call_id = str(tc_norm.get("id") or f"call_{hash(tool_name)}_{idx}")

        bridge = get_bridge()
        if bridge and bridge.is_stop_requested():
            return ToolMessage(
                content='{"error": "Agent stopped by user"}',
                tool_call_id=tool_call_id, name=tool_name,
            )

        tool_args = reconstruct_broken_content(tool_name, tool_args)
        display_agent_action(idx + 1, tool_name, tool_args)

        if bridge:
            args_preview = ", ".join(
                f"{k}={repr(v)[:40]}" for k, v in list(tool_args.items())[:3]
            )
            bridge.on_action(tool_name, args_preview)
            if tool_name in self._FILE_TOOLS:
                fpath = tool_args.get("file_path", tool_args.get("path", ""))
                if fpath:
                    bridge.on_file_working(str(fpath))

        tool = self.tool_map.get(tool_name)
        if tool is None:
            result = {
                "error": "unknown_tool",
                "tool": tool_name,
                "available": list(self.tool_map.keys()),
            }
        else:
            try:
                result = tool.invoke(tool_args)
            except Exception as e:
                result = {"error": type(e).__name__, "detail": str(e)}

        parsed = result if isinstance(result, (dict, list)) else str(result)
        display_tool_result(idx + 1, tool_name, parsed)

        if bridge:
            bridge.on_tool_result(tool_name, parsed)
            if tool_name in self._FILE_TOOLS and isinstance(parsed, dict):
                content = parsed.get("content", "")
                fpath = parsed.get("file_path", parsed.get("path", ""))
                if content and fpath:
                    lang = "python"
                    ext = str(fpath).rsplit(".", 1)[-1] if "." in str(fpath) else ""
                    lang_map = {
                        "js": "javascript", "ts": "typescript", "tsx": "typescript",
                        "json": "json", "md": "markdown", "css": "css",
                        "html": "html", "sh": "bash", "yaml": "yaml", "yml": "yaml",
                    }
                    lang = lang_map.get(ext, "python")
                    bridge.on_code(str(content)[:3000], lang, str(fpath))
                if parsed.get("action") in ("edited", "written", "created"):
                    bridge.on_file_changed(str(fpath))

        content_str = annotate_errors(tool_name, result)
        return ToolMessage(
            content=content_str, tool_call_id=tool_call_id, name=tool_name,
        )

    def _execute_tools(self, state: MessagesState) -> Dict[str, List[Any]]:
        """Execute tool calls — read-only tools in parallel, write tools sequentially."""
        messages = state["messages"]
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if not tool_calls:
            return {"messages": []}

        normalized = []
        for tc in tool_calls:
            normalized.append(normalize_tool_call(tc))

        # Split into read-only (parallelizable) and write (sequential)
        all_read_only = all(
            str(tc.get("name") or "") in self._READ_ONLY_TOOLS
            for tc in normalized
        )

        results: List[Any] = [None] * len(normalized)

        if all_read_only and len(normalized) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(normalized))) as pool:
                futures = {}
                for idx, tc_norm in enumerate(normalized):
                    future = pool.submit(self._run_single_tool, idx, tc_norm)
                    futures[future] = idx
                for future in as_completed(futures):
                    idx = futures[future]
                    results[idx] = future.result()
        else:
            for idx, tc_norm in enumerate(normalized):
                results[idx] = self._run_single_tool(idx, tc_norm)

        return {"messages": [r for r in results if r is not None]}

    @staticmethod
    def _should_continue(state: MessagesState) -> str:
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "tools"
        return END

    # ─── Graph construction ─────────────────────────────────────

    def _build(self):
        workflow = StateGraph(state_schema=MessagesState)
        workflow.add_node("agent", self._call_model)
        workflow.add_node("tools", self._execute_tools)
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges(
            "agent", self._should_continue,
            {"tools": "tools", END: END},
        )
        workflow.add_edge("tools", "agent")
        return workflow.compile()

    def stream(self, input_data, **kwargs):
        """Proxy to compiled graph's stream method."""
        return self._app.stream(input_data, **kwargs)

    def rebuild(self, llm_with_tools, model_name: str, is_reasoning: bool = False):
        """Update the LLM binding without rebuilding the graph structure."""
        self.llm_with_tools = llm_with_tools
        self.model_name = model_name
        self.is_reasoning = is_reasoning
        self.parallel_tools_disabled = False
