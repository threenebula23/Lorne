"""LangGraph agent graph: call_model / execute_tools / workflow compilation."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, StateGraph, MessagesState

from .spinner import LiveSpinner
from .message_utils import (
    sanitize_messages, is_retriable_bind_error, is_transient_error,
    strip_think_tags, extract_thought_segments, normalize_tool_call,
    coerce_assistant_content_to_text, extract_reasoning_from_response,
    reconstruct_broken_content,
    annotate_errors, MAX_LLM_RETRIES, coalesce_lc_response_tool_calls,
    extract_textual_tool_calls, extract_structured_tool_calls,
    summarize_tool_like_final_answer,
)

try:
    from Interface.visualization import (
        display_agent_action, display_tool_result, print_warning, print_error, print_thinking,
    )
except ImportError:
    def display_agent_action(sn, name, args): print(f"  Tool: {name}")
    def display_tool_result(sn, name, result):
        print(f"  Result: {name}")
        try:
            b = get_bridge()
            if b:
                b.on_tool_result(name, result)
        except Exception:
            pass
    def print_warning(m): print(f"  ⚠ {m}")
    def print_error(m): print(f"  ✗ {m}")
    def print_thinking(t=""): print(f"  Thinking: {t}")

try:
    from Interface.tui_bridge import get_bridge
except ImportError:
    def get_bridge(): return None

try:
    from .tool_schemas import validate_tool_arguments
except ImportError:
    from Agent.tool_schemas import validate_tool_arguments


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

        content = coerce_assistant_content_to_text(getattr(raw_response, "content", ""))
        meta = getattr(raw_response, "response_metadata", None) or {}
        if isinstance(content, str):
            content = content.encode("utf-8", "ignore").decode("utf-8", "ignore")

        thought_segments, content = extract_thought_segments(content)
        extra_thoughts = extract_reasoning_from_response(raw_response)
        all_thoughts: List[str] = []
        seen_thoughts: set[str] = set()
        for thought in thought_segments + extra_thoughts:
            t = (thought or "").strip()
            if not t or t in seen_thoughts:
                continue
            seen_thoughts.add(t)
            all_thoughts.append(t)

        for thought in all_thoughts:
            if thought:
                print_thinking(thought)
                bridge = get_bridge()
                if bridge:
                    bridge.on_thought(thought)

        content = strip_think_tags(content)

        merged_tool_calls = coalesce_lc_response_tool_calls(raw_response)
        if merged_tool_calls:
            return {"messages": [AIMessage(
                content=content or "",
                tool_calls=merged_tool_calls,
                response_metadata=meta,
            )]}

        structured_tool_calls = extract_structured_tool_calls(content)
        if structured_tool_calls:
            return {"messages": [AIMessage(
                content="",
                tool_calls=structured_tool_calls,
                response_metadata=meta,
            )]}

        textual_tool_calls, body = extract_textual_tool_calls(content)
        if textual_tool_calls:
            return {"messages": [AIMessage(
                content=body or "",
                tool_calls=textual_tool_calls,
                response_metadata=meta,
            )]}

        if isinstance(content, str):
            recent_tool_ctx = any(isinstance(m, ToolMessage) for m in messages[-4:])
            if recent_tool_ctx:
                humanized = summarize_tool_like_final_answer(content)
                if humanized:
                    content = humanized

        return {"messages": [AIMessage(content=content, response_metadata=meta)]}

    _READ_ONLY_TOOLS = frozenset({
        "read_file", "list_files", "search_in_files", "rag_search",
        "get_file_line_count", "load_plan",
        "web_search", "web_fetch",
        "ocr_tool",
        "office_document_read",
        "library_context",
        "reasoning_tool",
    })

    _FILE_TOOLS = frozenset({
        "read_file", "edit_file", "write_file", "code_file_tool",
        "replace_file_lines", "insert_file_lines",
        "docx_write_tool", "docxedit_tool", "docx_document_advanced_ops",
        "pdf_styled_document_create",
        "file_versions_tool",
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
        tool_args, val_err = validate_tool_arguments(tool_name, tool_args)
        if val_err:
            err_body = {
                "error": "argument_validation",
                "detail": val_err,
                "hint": "Проверь типы и обязательные поля; не дублируй вызовы — один инструмент за раз с полным набором аргументов.",
            }
            content_str = annotate_errors(tool_name, err_body)
            return ToolMessage(
                content=content_str, tool_call_id=tool_call_id, name=tool_name,
            )

        display_agent_action(idx + 1, tool_name, tool_args)

        if bridge:
            args_preview = ", ".join(
                f"{k}={repr(v)[:40]}" for k, v in list(tool_args.items())[:3]
            )
            bridge.on_action(tool_name, args_preview)
            if tool_name in self._FILE_TOOLS:
                fpath = tool_args.get(
                    "file_path", tool_args.get("path", tool_args.get("filename", "")),
                )
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

        if bridge and tool_name in self._FILE_TOOLS and isinstance(parsed, dict):
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
            if fpath and parsed.get("action") in (
                "edited", "written", "created", "created_file",
                "lines_replaced", "lines_inserted", "code_written", "snippet_appended",
                "appended", "patched", "pdf_created",
            ):
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
