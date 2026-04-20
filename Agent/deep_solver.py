"""Deep Solver — long-running, local-only autonomous coding agent.

This mode is explicitly **not** a chat: once started it keeps the model
running for hours on a single coarse-grained task (e.g. "build me a
beautiful website"), self-generating sub-goals, committing checkpoints
that the user can rewind or seed further prompts from, and using the
local Ollama model only — remote provider keys are intentionally
ignored here to keep long runs free/offline.

Key behaviours compared to the normal React loop:
  • Deep system prompt forbids `ask_user`; anything that would normally
    require user input is replaced with a best-effort decision + a
    checkpoint so the user can redirect from the UI.
  • Every ``_CHECKPOINT_EVERY_STEPS`` tool rounds we persist a
    ``(messages, workspace)`` snapshot via the existing checkpoint
    machinery and mount a ``DeepCheckpointBlock`` card in the chat.
  • Long histories are compacted with
    :func:`Agent.message_utils.compact_conversation` on a sliding window
    to keep the prompt below the local ``num_ctx``.
  • A verified-facts ledger (``### Подтверждённые факты``) is injected
    before each LLM call to reduce hallucination — the model must ground
    claims in that list instead of inventing project state.
  • Heavy subtasks can be delegated to Creator Mode by emitting a
    special ``spawn_subagent`` tool-call; this reuses the existing
    parallel-worker machinery without polluting the main tool registry.
  • Stop flag checked every round. On stop: the model is given one last
    turn to summarize what it accomplished; that summary is returned to
    the agent loop which shows it as the final reply.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

try:
    from .creator_provider import get_local_llm, get_creator_config, check_local_server
    from .llm_provider import (
        get_available_models,
        get_saved_model,
        _load_ui_model_overrides,
    )
    from .tool_registry import bind_tools_safe
    from .message_utils import (
        coalesce_lc_response_tool_calls,
        coerce_assistant_content_to_text,
        extract_structured_tool_calls,
        extract_textual_tool_calls,
        normalize_tool_call,
        reconstruct_broken_content,
        compact_conversation,
        sanitize_messages,
        extract_thought_segments,
    )
    from .tool_schemas import validate_tool_arguments
    from .checkpoint import (
        save_pre_turn_snapshot,
        save_pre_turn_workspace_snapshot,
        load_pre_turn_snapshot,
        restore_turn_workspace,
        delete_turn_snapshots_from,
        delete_turn_workspace_snapshots_from,
        messages_from_stored_dicts,
        save_state,
    )
except ImportError:  # pragma: no cover — fallback for direct execution
    from Agent.creator_provider import get_local_llm, get_creator_config, check_local_server
    from Agent.llm_provider import (
        get_available_models,
        get_saved_model,
        _load_ui_model_overrides,
    )
    from Agent.tool_registry import bind_tools_safe
    from Agent.message_utils import (
        coalesce_lc_response_tool_calls,
        coerce_assistant_content_to_text,
        extract_structured_tool_calls,
        extract_textual_tool_calls,
        normalize_tool_call,
        reconstruct_broken_content,
        compact_conversation,
        sanitize_messages,
        extract_thought_segments,
    )
    from Agent.tool_schemas import validate_tool_arguments
    from Agent.checkpoint import (
        save_pre_turn_snapshot,
        save_pre_turn_workspace_snapshot,
        load_pre_turn_snapshot,
        restore_turn_workspace,
        delete_turn_snapshots_from,
        delete_turn_workspace_snapshots_from,
        messages_from_stored_dicts,
        save_state,
    )


# ─── Local-model resolver ─────────────────────────────────────────────
#
# Deep Solver runs *only* against a model physically hosted on the user's
# machine (Ollama daemon, LM Studio, llama.cpp, …). We therefore resolve
# which model to use in three layers, in priority order:
#   1. The model currently selected in the UI dropdown (``get_saved_model``).
#      If it's ``ollama/<name>`` or ``tier == "local"`` in the prefs list,
#      we use it — same Ollama base URL as the main agent would.
#   2. One of the user-added Ollama custom models (first one, so that a
#      user who added exactly one model doesn't have to "select" it).
#   3. Creator Mode fallback (``get_creator_config()["local_model"]``).
# If none of those resolve to an Ollama-style model, we refuse to start
# and explain what needs to be picked — far clearer than letting the run
# silently proxy through a remote endpoint.

def _build_local_llm(model_name: str, base_url: str) -> Any:
    """Build an LLM object tied to the user's local machine.

    Tries ChatOllama native first (better tool-call handling, honours
    ``num_ctx`` / ``top_k`` / ``repeat_penalty``), falls back to the
    Creator helper ``get_local_llm`` which picks OpenAI-compat transport
    when the URL looks like OpenWebUI / LM Studio / vLLM.
    """
    try:
        try:
            from .llm_provider import _build_ollama_chat_llm, _resolve_ollama_settings
        except ImportError:
            from Agent.llm_provider import _build_ollama_chat_llm, _resolve_ollama_settings

        import os as _os
        prev = _os.environ.get("OLLAMA_BASE_URL")
        if base_url:
            _os.environ["OLLAMA_BASE_URL"] = base_url
        try:
            settings = _resolve_ollama_settings(model_name, 0.3, 8192)
            return _build_ollama_chat_llm(model_name, settings)
        finally:
            if prev is None:
                _os.environ.pop("OLLAMA_BASE_URL", None)
            else:
                _os.environ["OLLAMA_BASE_URL"] = prev
    except Exception:
        # Fallback via the Creator helper (handles OpenAI-compat endpoints).
        return get_local_llm(model_name=model_name, base_url=base_url,
                             temperature=0.3, max_tokens=8192)


def _resolve_deep_local_model() -> Dict[str, Any]:
    """Return ``{"model_name", "base_url", "source"}`` for the Deep run.

    ``model_name`` never contains the ``ollama/`` prefix — it's the raw
    name that Ollama's API expects (e.g. ``qwen2.5-coder:7b``).
    ``source`` is one of ``"ui"``, ``"prefs_first"``, ``"creator_fallback"``.
    """
    prefs = _load_ui_model_overrides() or {}
    custom = prefs.get("ollama_custom_models") or []
    known_local: Dict[str, Dict[str, Any]] = {}
    for m in custom:
        if isinstance(m, dict):
            nm = str(m.get("name") or "").strip()
            if nm:
                known_local[nm] = m

    # 1. UI selection.
    saved = get_saved_model() or ""
    if saved.startswith("ollama/"):
        name = saved.split("/", 1)[1]
        return {
            "model_name": name,
            "base_url": str(prefs.get("ollama_base_url") or
                            get_creator_config().get("local_base_url") or ""),
            "source": "ui",
        }

    # 2. First Ollama custom model.
    if known_local:
        first_name = next(iter(known_local.keys()))
        return {
            "model_name": first_name,
            "base_url": str(prefs.get("ollama_base_url") or
                            get_creator_config().get("local_base_url") or ""),
            "source": "prefs_first",
        }

    # 3. Creator fallback.
    cfg = get_creator_config()
    return {
        "model_name": str(cfg.get("local_model") or ""),
        "base_url": str(cfg.get("local_base_url") or ""),
        "source": "creator_fallback",
    }


# ─── Tunables ─────────────────────────────────────────────────────────

_MAX_STEPS = 800                # hard ceiling — 800 tool rounds ≈ many hours
_CHECKPOINT_EVERY_STEPS = 6     # auto-checkpoint cadence
_COMPACT_EVERY_STEPS = 12       # run compaction every N rounds
_KEEP_LAST_AFTER_COMPACT = 10   # keep the tail intact
_MAX_FACTS = 40                 # verified-facts ledger cap
_SUBAGENT_TOOL_NAME = "spawn_subagent"
_GET_SUBAGENT_TOOL_NAME = "get_subagent_result"
_FINAL_DONE_TOOL_NAME = "deep_final_done"
# ``deep_final_done`` is rejected until *both* thresholds are met — stops
# local models from declaring «всё готово» after a shallow MVP pass and
# encourages tests / docs / polish / verification runs.
# Override for tiny tasks: ``TCA_DEEP_MIN_RUNTIME_SEC=0 TCA_DEEP_MIN_STEPS=0``.
_MIN_RUNTIME_BEFORE_FINAL_SEC = max(
    0, int(os.environ.get("TCA_DEEP_MIN_RUNTIME_SEC", str(20 * 60)))
)
_MIN_STEPS_BEFORE_FINAL = max(
    0, int(os.environ.get("TCA_DEEP_MIN_STEPS", "40"))
)


# ─── Registry of live Deep runs, keyed by checkpoint id ───────────────
# Used by the UI when the user clicks "Откат" / "Продолжить" on a
# checkpoint card so the action can find the session that owns it.

_DEEP_CHECKPOINT_INDEX: Dict[str, Dict[str, Any]] = {}
_DEEP_CHECKPOINT_LOCK = threading.Lock()


# ─── Singleton Deep session state ─────────────────────────────────────
#
# The Deep loop is intentionally a singleton: when the user sends a
# chat message mid-run, we must **not** spawn a second Deep instance
# (that would double-run the model and confuse the output). Instead we
# push the message into ``_DEEP_STATE.inbox`` and the running loop
# consumes it at the start of the next iteration.
#
# ``handle_chat_submit`` in ``Agent/agent.py`` checks ``is_running()``
# before starting a new run; if one is already alive, it calls
# :func:`submit_user_message` and returns.

class _DeepState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.started_at: float = 0.0
        self.inbox: List[str] = []
        self.original_goal: str = ""
        self.last_checkpoint_ts: float = 0.0
        self.checkpoint_count: int = 0

    def start(self, goal: str) -> None:
        with self.lock:
            self.running = True
            self.started_at = time.time()
            self.last_checkpoint_ts = self.started_at
            self.inbox = []
            self.original_goal = goal
            self.checkpoint_count = 0

    def stop(self) -> None:
        with self.lock:
            self.running = False

    def is_running(self) -> bool:
        with self.lock:
            return self.running

    def push_message(self, text: str) -> bool:
        with self.lock:
            if not self.running:
                return False
            self.inbox.append(text)
            return True

    def drain_messages(self) -> List[str]:
        with self.lock:
            out = list(self.inbox)
            self.inbox.clear()
            return out

    def mark_checkpoint(self) -> Dict[str, float]:
        """Return ``{"total": float, "since_prev": float}`` for the just-made
        checkpoint. Updates the internal clock after measuring."""
        now = time.time()
        with self.lock:
            self.checkpoint_count += 1
            since_prev = now - (self.last_checkpoint_ts or self.started_at or now)
            self.last_checkpoint_ts = now
            total = now - (self.started_at or now)
        return {"total": total, "since_prev": since_prev}

    def elapsed(self) -> float:
        with self.lock:
            if not self.started_at:
                return 0.0
            return time.time() - self.started_at


_DEEP_STATE = _DeepState()


def is_running() -> bool:
    """True if a Deep Solver run is currently active in this process."""
    return _DEEP_STATE.is_running()


def submit_user_message(text: str) -> bool:
    """Feed a mid-run user message into the live Deep loop.

    Returns True if the message was queued (run is active), False otherwise
    (caller should start a new run or behave normally).
    """
    return _DEEP_STATE.push_message(text or "")


def _format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}ч {m:02d}м {s:02d}с"
    if m:
        return f"{m}м {s:02d}с"
    return f"{s}с"


def register_checkpoint(cp_id: str, session_id: str, turn_index: int,
                        title: str) -> None:
    with _DEEP_CHECKPOINT_LOCK:
        _DEEP_CHECKPOINT_INDEX[cp_id] = {
            "session_id": session_id,
            "turn_index": int(turn_index),
            "title": title,
            "ts": time.time(),
        }


def get_checkpoint(cp_id: str) -> Optional[Dict[str, Any]]:
    with _DEEP_CHECKPOINT_LOCK:
        entry = _DEEP_CHECKPOINT_INDEX.get(cp_id)
        return dict(entry) if entry else None


def clear_checkpoint(cp_id: str) -> None:
    with _DEEP_CHECKPOINT_LOCK:
        _DEEP_CHECKPOINT_INDEX.pop(cp_id, None)


# ─── System prompt ────────────────────────────────────────────────────

_DEEP_SYSTEM_PROMPT_TEMPLATE = """Ты — автономный разработчик в режиме **Deep Solver**.

Ниже указана **главная цель** пользователя. Она — единственный источник
истины о том, что должно быть сделано. Всё, что ты делаешь, должно
прямо служить этой цели.

## 🎯 Главная цель (неизменна до конца сессии)
{goal}

## Жёсткие правила фокуса (нарушать запрещено)

- Прежде чем действовать, ВСЕГДА сверяйся с главной целью выше.
  Если твой следующий шаг не продвигает эту цель — отмени его и выбери
  другой.
- Не придумывай новых тем. Не пиши код «для красоты», который никак
  не связан с главной целью. Улучшения допустимы только если они
  явно улучшают результат главной цели (UI/UX/документация основного
  проекта, тесты его кода, оптимизация его производительности).
- Если вдруг заметил, что «уехал в сторону» (начал делать что-то
  постороннее, например переписывать несвязанный файл или пилить левый
  проект) — сразу вызови `deep_checkpoint` с title «возврат к цели»
  и вернись к главной задаче.

## Правила режима

1. **Никогда не спрашивай пользователя.** Инструмент `ask_user` запрещён.
   Если нужно принять решение — выбери лучший вариант по смыслу главной
   цели и сделай. Пользователь сам направит тебя через чат.
2. **Мид-ран сообщения пользователя.** Тебе могут прилететь сообщения
   вида `[user interjection]: …`. Отнесись к ним как к уточнению
   главной цели, интегрируй их в рабочий план и продолжай работу —
   **не начинай заново**, не трать токены на поклоны, просто учти и
   иди дальше.
3. **Сам выставляй подцели.** После каждой выполненной подзадачи задай
   следующий маленький шаг в сторону главной цели. Не пиши «готово,
   жду», пока `deep_final_done` не вызван.
4. **Выдвигай 2-3 гипотезы перед серьёзным шагом.** Кратко сравни их
   (1-2 строки на гипотезу) и действуй той, которая лучше отвечает
   главной цели и состоянию кода на диске.
5. **Используй терминал смело.** Можешь запускать команды, ставить
   зависимости, создавать каталоги — всё без подтверждений.
6. **Делай чекпоинты сам.** После каждого завершённого логического
   шага вызови `deep_checkpoint` с title и summary. Это единственный
   способ позволить пользователю откатиться.
7. **Делегирование и параллель.** `spawn_subagent(task=...)` запускает
   Creator Mode **в фоне** (не блокирует твой поток). Сразу получишь `token`.
   Пока крутится долгий `run_command` (сервер, сборка 120 с) — не жди тест
   в том же коллбэке: либо сначала `spawn_subagent` с микрозадачей «потом
   проверь curl/health», либо в обычном чате доступен `start_background_task`
   (см. основной промпт TCA). Когда нужен отчёт воркеров — вызови
   `get_subagent_result(token, wait_seconds=...)`. Для очень больших задач
   опиши `task` подробно.
8. **Не галлюцинируй.** Прежде чем писать про файл/функцию —
   прочитай её (`read_file_lines` для больших файлов). Не ссылайся на
   то, чего нет в «Подтверждённых фактах» или в текущих тул-результатах.
9. **Завершение сессии (`deep_final_done`).** Вызывай **только** когда
   одновременно: (а) прошло не меньше ~20 минут активной работы,
   (б) выполнено много шагов с тулами, (в) ты реально прогнал проверки
   качества: тесты, README/доки, сборка или линтер, просмотрел критичные
   файлы. До этого момента **запрещено** закрывать сессию одним отчётом
   «всё создано» — после MVP продолжай улучшать, пока не исчерпан смысл
   или пользователь не нажал «Стоп».

## Формат мышления

Перед **серьёзным** шагом (новая подзадача, архитектурный выбор, большая
правка) коротко проговаривай:
  • Главная цель → как мой шаг её продвигает
  • Гипотезы: 1) … 2) … 3) …
  • Выбор и почему
  • Следующий тул

Для мелочёвки (прочитать файл, поправить строчку) этот блок НЕ
нужен — сразу вызывай тул. Никогда не повторяй «## Главная цель» /
«## Гипотезы» на каждом ответе — это шум и съедает контекст.

Если пользователь задал вопрос ( `[user question]` или `?` в
конце) — отвечай живым языком 1-3 предложения, БЕЗ markdown-заголовков
про цель/гипотезы, БЕЗ вызова тулов на этот ответ; после него
продолжишь работу.

Пиши по-русски, код — на языке проекта. Комментарии в коде только там,
где они добавляют смысл (не повторяй, что видно из кода).
"""


def _facts_prompt(facts: List[str]) -> str:
    if not facts:
        return ("### Подтверждённые факты\n"
                "(пока пусто — ничего не предполагай о проекте, сначала "
                "прочитай нужные файлы)\n")
    bullets = "\n".join(f"- {f}" for f in facts[-_MAX_FACTS:])
    return "### Подтверждённые факты\n" + bullets + "\n"


# ─── Helpers ──────────────────────────────────────────────────────────

def _inject_or_replace_system(messages: List[Any], prompt: str) -> None:
    """Ensure the first message is exactly ``prompt``; update in place."""
    if messages and isinstance(messages[0], SystemMessage):
        messages[0] = SystemMessage(content=prompt)
    else:
        messages.insert(0, SystemMessage(content=prompt))


def _extract_facts(tool_name: str, result: Any) -> List[str]:
    """Heuristic: derive 0-2 short verified facts from a tool result."""
    out: List[str] = []
    try:
        if tool_name in ("read_file", "read_file_lines"):
            if isinstance(result, dict):
                fn = (
                    result.get("file_path")
                    or result.get("filename")
                    or result.get("path")
                    or "?"
                )
                size = result.get("total_lines") or result.get("lines") or "?"
                out.append(f"Прочитан файл {fn} ({size} строк)")
        elif tool_name in ("write_file", "create_file", "replace_file_lines",
                           "insert_file_lines", "apply_patch"):
            if isinstance(result, dict):
                fn = result.get("filename") or result.get("path") or "?"
                out.append(f"Записан/изменён файл {fn}")
        elif tool_name in ("run_command", "terminal_run"):
            if isinstance(result, dict):
                rc = result.get("return_code")
                if rc is not None:
                    out.append(f"Команда завершилась с кодом {rc}")
        elif tool_name == "list_files":
            if isinstance(result, dict):
                items = (
                    result.get("entries")
                    or result.get("files")
                    or result.get("items")
                    or []
                )
                if items:
                    out.append(f"Список каталога: {len(items)} записей")
    except Exception:
        pass
    return out


def _render_tool_result(result: Any, *, hard_limit: int = 3000) -> str:
    if isinstance(result, (dict, list)):
        content = json.dumps(result, ensure_ascii=False, default=str)
    else:
        content = str(result)
    if len(content) > hard_limit:
        half = hard_limit // 2
        content = (content[:half]
                   + f"\n…[+{len(content) - hard_limit} симв.]…\n"
                   + content[-half:])
    return content


def _compact_with_head_lock(messages: List[Any], *, head_lock: int,
                            keep_last: int) -> List[Any]:
    """Compact ``messages`` while protecting the first ``head_lock`` system
    messages (goal pin, project context, facts ledger) from summarisation.
    """
    if len(messages) <= head_lock + keep_last + 2:
        return messages
    head = messages[:head_lock]
    tail = messages[head_lock:]
    compacted_tail = compact_conversation(tail, keep_last=keep_last)
    # compact_conversation re-prepends SystemMessages; we just overwrite head.
    # Drop any stray SystemMessage at the start of compacted_tail so we
    # don't end up with two roles fighting for priority.
    while compacted_tail and isinstance(compacted_tail[0], SystemMessage):
        compacted_tail.pop(0)
    return list(head) + compacted_tail


def _filter_tools_for_deep(tools: List[BaseTool]) -> List[BaseTool]:
    """Drop tools that require human interaction from the Deep toolset."""
    banned = {"ask_user", "user_confirm", "confirm_action"}
    kept: List[BaseTool] = []
    for t in tools:
        name = str(getattr(t, "name", "") or "")
        if name in banned:
            continue
        kept.append(t)
    return kept


_SUBAGENT_ASYNC_JOBS: Dict[str, Dict[str, Any]] = {}
_SUBAGENT_ASYNC_LOCK = threading.Lock()


def _start_subagent_async(
    sub_task: str,
    tools: List[BaseTool],
    project_context: str,
    bridge: Any,
) -> str:
    token = f"sub_{uuid.uuid4().hex[:10]}"
    ev = threading.Event()
    with _SUBAGENT_ASYNC_LOCK:
        _SUBAGENT_ASYNC_JOBS[token] = {
            "status": "running",
            "result": None,
            "error": None,
            "event": ev,
        }

    def _worker() -> None:
        try:
            r = _run_subagent(sub_task, tools, project_context, bridge)
            with _SUBAGENT_ASYNC_LOCK:
                if token in _SUBAGENT_ASYNC_JOBS:
                    _SUBAGENT_ASYNC_JOBS[token]["result"] = r
                    _SUBAGENT_ASYNC_JOBS[token]["status"] = "done"
        except Exception as e:
            with _SUBAGENT_ASYNC_LOCK:
                if token in _SUBAGENT_ASYNC_JOBS:
                    _SUBAGENT_ASYNC_JOBS[token]["error"] = str(e)
                    _SUBAGENT_ASYNC_JOBS[token]["status"] = "error"
        finally:
            with _SUBAGENT_ASYNC_LOCK:
                if token in _SUBAGENT_ASYNC_JOBS:
                    _SUBAGENT_ASYNC_JOBS[token]["event"].set()

    threading.Thread(target=_worker, name=f"deep-subagent-{token}", daemon=True).start()
    return token


def _join_subagent(token: str, wait_seconds: float) -> Dict[str, Any]:
    with _SUBAGENT_ASYNC_LOCK:
        j = _SUBAGENT_ASYNC_JOBS.get(token)
    if not j:
        return {"ok": False, "error": "unknown_subagent_token", "token": token}
    if wait_seconds and wait_seconds > 0:
        j["event"].wait(timeout=float(wait_seconds))
    with _SUBAGENT_ASYNC_LOCK:
        j2 = dict(_SUBAGENT_ASYNC_JOBS.get(token) or {})
    st = j2.get("status")
    if st == "running":
        return {
            "ok": True,
            "status": "running",
            "token": token,
            "hint": "Повтори get_subagent_result с wait_seconds > 0.",
        }
    if st == "error":
        return {"ok": False, "error": j2.get("error"), "token": token}
    return {"ok": True, "status": "done", "data": j2.get("result"), "token": token}


def _build_deep_extra_tools() -> List[BaseTool]:
    """Define Deep-specific stub tools (checkpoint / subagent / done).

    They are Python-native ``@tool`` functions so the local model can emit
    them as regular tool-calls; the run-loop intercepts them before
    dispatch so their actual behaviour lives here, not in the registry.
    """
    from langchain_core.tools import tool

    @tool
    def deep_checkpoint(title: str, summary: str = "") -> str:
        """Зафиксируй логический чекпоинт прогресса.

        Вызывай после каждого завершённого этапа (готов скелет, сверстан UI,
        прошли тесты и т.п.). ``title`` — короткий заголовок (до 60 симв.),
        ``summary`` — 1-3 строки про то, что сейчас сделано.
        """
        return f"checkpoint_saved: {title}"

    @tool
    def spawn_subagent(task: str) -> str:
        """Старт **асинхронного** sub-agent (Creator) — не жди на этом шаге.

        Получи `token` в ответе, затем `get_subagent_result(token, wait_seconds)`.
        """
        return f"subagent_start: {task[:80]}"

    @tool
    def get_subagent_result(token: str, wait_seconds: int = 0) -> str:
        """Дождись или проверь статус sub-agent по `token` из `spawn_subagent`."""
        return f"get_subagent: {token[:12]}"

    @tool
    def deep_final_done(report: str) -> str:
        """Заверши Deep-сессию с итоговым отчётом.

        Вызывай только когда проект действительно готов (основная задача +
        документация + полировка). ``report`` — 5-15 строк о том, что
        сделано и где это живёт.
        """
        return f"deep_done: {report[:120]}"

    return [deep_checkpoint, spawn_subagent, get_subagent_result, deep_final_done]


# ─── Public entrypoint ────────────────────────────────────────────────

def run_deep_solver(
    task: str,
    tools: List[BaseTool],
    bridge: Any,
    project_context: str = "",
    session_id: str = "",
    messages: Optional[List[Any]] = None,
) -> str:
    """Run the Deep Solver loop until stop / final_done / step-cap.

    Returns the final summary text to be shown as the assistant reply
    (also appended to ``messages`` by the caller).
    """
    resolved = _resolve_deep_local_model()
    model_name = resolved.get("model_name") or ""
    base_url = resolved.get("base_url") or ""
    source = resolved.get("source")

    if not model_name:
        msg = (
            "⚠ Deep Solver работает только с **локальной** моделью, но ни "
            "в выбранной модели, ни в настройках Ollama не найдено подходящей. "
            "Открой настройки → вкладка Ollama, добавь свою локальную модель "
            "(кнопка «Добавить модель»), затем выбери её в выпадающем списке "
            "рядом с полем ввода."
        )
        try:
            bridge.on_error(msg)
        except Exception:
            pass
        return msg

    # Сообщим пользователю, откуда взялась модель, — проще дебажить
    # ситуацию "я выбрал в UI одно, а сервер поехал к другому".
    try:
        src_label = {
            "ui": "выбрана в UI",
            "prefs_first": "первая из Ollama-моделей в настройках",
            "creator_fallback": "из настроек Creator Mode",
        }.get(source or "", source or "")
        bridge.on_info(
            f"🧠 Deep Solver: модель «{model_name}» ({src_label}), "
            f"URL {base_url or '—'}"
        )
    except Exception:
        pass

    # Probe is advisory only — different local stacks (Ollama native,
    # OpenWebUI, LM Studio, vLLM, …) expose different discovery endpoints,
    # so a False here does **not** mean the chat endpoint is dead. We warn
    # but still try to build the LLM; the real gate is whether
    # ``llm.invoke`` succeeds on the first call.
    try:
        probe_ok = bool(check_local_server(base_url))
    except Exception:
        probe_ok = False
    if not probe_ok:
        try:
            bridge.on_warning(
                "Не удалось автоматически проверить локальный сервер по "
                f"адресу {base_url or '—'} — продолжаем с выбранной моделью. "
                "Если первый запрос к модели упадёт, проверь URL и ключ."
            )
        except Exception:
            pass

    try:
        llm = _build_local_llm(model_name, base_url)
    except Exception as e:
        err = f"Не удалось поднять локальную модель «{model_name}»: {e}"
        try:
            bridge.on_error(err)
        except Exception:
            pass
        return err

    filtered_tools = _filter_tools_for_deep(tools)
    extra_tools = _build_deep_extra_tools()
    all_tools = filtered_tools + extra_tools
    tool_map: Dict[str, BaseTool] = {}
    for t in all_tools:
        nm = getattr(t, "name", None) or getattr(t, "__name__", None)
        if nm:
            tool_map[str(nm)] = t

    llm_bound = bind_tools_safe(llm, model_name, all_tools)

    # Goal pinned in the system prompt so it never gets compacted away.
    system_prompt = _DEEP_SYSTEM_PROMPT_TEMPLATE.format(goal=task.strip())

    conversation: List[Any] = [SystemMessage(content=system_prompt)]
    if project_context:
        conversation.append(SystemMessage(
            content="### Контекст проекта\n" + str(project_context)[:4000]
        ))
    conversation.append(SystemMessage(content=_facts_prompt([])))
    conversation.append(HumanMessage(content=task))

    # Number of SystemMessages at the head we must never compact away.
    head_lock = sum(1 for m in conversation if isinstance(m, SystemMessage))

    facts: List[str] = []
    steps = 0
    final_report = ""
    stopped_by_user = False

    _DEEP_STATE.start(goal=task.strip())

    # Suppress the terminal "Run command?" confirmation modal for the whole
    # Deep run — the mode is *defined* as autonomous, interactive prompts
    # would block the loop forever. We restore the previous value in the
    # ``finally`` block so Normal/Agent chats keep their confirmations.
    try:
        from Agent.tools import terminal_tool as _term_tool
    except ImportError:  # pragma: no cover
        _term_tool = None  # type: ignore
    prev_auto_confirm = getattr(_term_tool, "AUTO_CONFIRM", False) if _term_tool else False
    if _term_tool is not None:
        _term_tool.AUTO_CONFIRM = True

    # Heartbeat — refreshes the elapsed-time badge above the input
    # field every second. Stops automatically when ``_DEEP_STATE.stop()``
    # is called in the ``finally`` below.
    _hb_stop = threading.Event()

    def _heartbeat() -> None:
        while not _hb_stop.is_set():
            try:
                if hasattr(bridge, "on_deep_status"):
                    bridge.on_deep_status(
                        running=True,
                        elapsed=_format_elapsed(_DEEP_STATE.elapsed()),
                        checkpoints=_DEEP_STATE.checkpoint_count,
                        model=model_name,
                    )
            except Exception:
                pass
            _hb_stop.wait(1.0)

    hb_thread = threading.Thread(target=_heartbeat, name="deep-heartbeat",
                                 daemon=True)
    hb_thread.start()

    # Tell the chat panel what the actual context window of the picked
    # model is so the meter above the input reflects reality — local
    # Ollama models frequently don't return usage metadata so without
    # this push the meter would just display the previous global limit.
    try:
        from Interface.visualization import get_context_limit as _gcl
        ctx_limit = int(_gcl(f"ollama/{model_name}") or 0) or 32_768
    except Exception:
        ctx_limit = 32_768
    try:
        bridge.on_context_update(0, ctx_limit)
    except Exception:
        pass

    try:
        bridge.on_info(
            f"🧠 Deep Solver запущен — модель «{model_name}», окно ~{ctx_limit:,} ток. "
            "Автоматические чекпоинты. Можешь писать сообщения прямо во время работы — "
            "они встанут в очередь и учтутся на следующем шаге (новый запуск НЕ начнётся)."
        )
    except Exception:
        pass

    try:
        while steps < _MAX_STEPS:
            if getattr(bridge, "is_stop_requested", lambda: False)():
                stopped_by_user = True
                break

            # Pull any user messages that arrived mid-run and append them
            # as a "[user interjection]" block so the model treats them as
            # a clarification, not a new task.
            #
            # Heuristic: if the interjection looks like a question about
            # current progress ("что делаешь", "где ты", "status", "?"),
            # tag it as [user question]. The model is then told in the
            # block body to answer *briefly* (1–3 предложения) without
            # re-stating the plan / hypotheses. This fixes the regression
            # where asking "что ты делаешь?" caused the model to re-dump
            # the entire "## Главная цель / ## Гипотезы" preamble.
            interjections = _DEEP_STATE.drain_messages()
            for text in interjections:
                txt = text.strip()
                if not txt:
                    continue
                lower = txt.lower()
                looks_question = (
                    txt.endswith("?")
                    or any(kw in lower for kw in (
                        "что ты ", "что делаешь", "что сейчас",
                        "где ты", "статус", "прогресс", "how is",
                        "what are you", "status", "progress",
                    ))
                )
                if looks_question:
                    conversation.append(HumanMessage(
                        content=(
                            "[user question — ответь коротко, 1-3 "
                            "предложения, не повторяй план и гипотезы, "
                            "не пиши «## Главная цель» / «## Гипотезы», "
                            "просто живым языком расскажи, на каком "
                            "этапе находишься и что только что сделал; "
                            "ни одного тул-колла на этот ответ, после "
                            "него продолжишь работу как обычно]:\n"
                            + txt
                        )
                    ))
                else:
                    conversation.append(HumanMessage(
                        content=(
                            "[user clarification — учти в текущем плане, "
                            "не начинай с нуля, не повторяй блок "
                            "«## Главная цель» / «## Гипотезы»]:\n" + txt
                        )
                    ))
                try:
                    bridge.on_info(
                        f"📨 {'Вопрос' if looks_question else 'Сообщение'} "
                        f"пользователя учтён(о) на шаге {steps + 1}"
                    )
                except Exception:
                    pass

            # Refresh the facts header (search all system messages at the head).
            for i in range(head_lock):
                m = conversation[i]
                if isinstance(m, SystemMessage) and str(m.content or "").startswith(
                        "### Подтверждённые факты"):
                    conversation[i] = SystemMessage(content=_facts_prompt(facts))
                    break

            if steps and steps % _COMPACT_EVERY_STEPS == 0:
                conversation = _compact_with_head_lock(
                    conversation, head_lock=head_lock,
                    keep_last=_KEEP_LAST_AFTER_COMPACT,
                )

            # Per-step guardrail: re-inject a brief reminder of the goal
            # right before the LLM call so a long compacted session can't
            # drift. Ephemeral — not persisted into conversation.
            probe_messages = list(conversation)
            probe_messages.append(SystemMessage(
                content=("### Напоминание\nГлавная цель пользователя: "
                         + task.strip()[:400]
                         + "\nКаждое твоё действие должно служить этой цели. "
                         + "Если следующий шаг не продвигает её — выбери другой.")
            ))

            try:
                response = llm_bound.invoke(sanitize_messages(probe_messages))
            except Exception as e:
                try:
                    bridge.on_error(f"LLM call failed: {e}")
                except Exception:
                    pass
                break

            content = coerce_assistant_content_to_text(getattr(response, "content", ""))
            meta = getattr(response, "response_metadata", None) or {}
            merged_tcs = coalesce_lc_response_tool_calls(response)

            if not merged_tcs:
                structured = extract_structured_tool_calls(content)
                if structured:
                    merged_tcs = structured
                    content = ""
                else:
                    textual, body = extract_textual_tool_calls(content)
                    if textual:
                        merged_tcs = textual
                        content = body or ""

            # Stream visible thoughts before acting.
            if content:
                try:
                    segs, visible = extract_thought_segments(content)
                except Exception:
                    segs, visible = [], content
                for th in segs:
                    if (th or "").strip():
                        try:
                            bridge.on_thought(th.strip())
                        except Exception:
                            pass
                visible = (visible or "").strip()
                if visible:
                    try:
                        bridge.on_model_reply(visible, None)
                    except Exception:
                        pass

            ai_msg = AIMessage(content=content, tool_calls=merged_tcs or [],
                               response_metadata=meta)
            conversation.append(ai_msg)

            if not merged_tcs:
                # No tool calls — nudge the model to keep going or wrap up.
                conversation.append(HumanMessage(
                    content=(
                        "Следующий ход — **только с вызовом инструментов** "
                        "(read_file, write_file, run_command, code_file_tool, …). "
                        "Не останавливайся на длинном тексте без тулов. Выбери "
                        "конкретную подзадачу по главной цели: тесты, документация, "
                        "сборка, рефакторинг, UI — и выполни её. Завершение сессии "
                        "(`deep_final_done`) только после длительной проверенной "
                        "работы (см. системный промпт), не сразу после черновика."
                    )
                ))
                steps += 1
                continue

            steps += 1

            # Dispatch each tool call.
            for tc in merged_tcs:
                tc_dict = normalize_tool_call(tc)
                tool_name = str(tc_dict.get("name", "")).strip()
                tool_args = reconstruct_broken_content(
                    tool_name, tc_dict.get("args", {}) or {}
                )
                tool_call_id = str(tc_dict.get("id", f"call_{uuid.uuid4().hex[:8]}"))

                # Intercept deep-specific tools before validation.
                if tool_name == "deep_checkpoint":
                    title = str(tool_args.get("title", "") or "Checkpoint")
                    summary = str(tool_args.get("summary", "") or "")
                    times = _DEEP_STATE.mark_checkpoint()
                    cp_idx = _DEEP_STATE.checkpoint_count
                    cp_id = (f"dcp_{session_id or 'anon'}_"
                             f"{int(time.time())}_{cp_idx}")
                    turn_idx = (sum(1 for m in messages if isinstance(m, HumanMessage))
                                if messages is not None else 0)
                    try:
                        if session_id and messages is not None:
                            save_pre_turn_snapshot(session_id, turn_idx, list(messages))
                            save_pre_turn_workspace_snapshot(session_id, turn_idx)
                    except Exception:
                        pass
                    register_checkpoint(cp_id, session_id, turn_idx, title)

                    elapsed_since_prev = _format_elapsed(times["since_prev"])
                    elapsed_total = _format_elapsed(times["total"])
                    summary_with_time = (
                        (summary + "\n" if summary else "")
                        + f"⏱ этап {elapsed_since_prev}  ·  сессия {elapsed_total}"
                    )

                    try:
                        bridge.on_deep_checkpoint(
                            cp_id=cp_id,
                            index=cp_idx,
                            title=title,
                            summary=summary_with_time,
                            turn_index=turn_idx,
                        )
                    except Exception:
                        pass

                    result_str = json.dumps(
                        {"ok": True, "cp_id": cp_id, "index": cp_idx,
                         "elapsed_since_prev_sec": int(times["since_prev"]),
                         "elapsed_total_sec": int(times["total"])},
                        ensure_ascii=False,
                    )
                    conversation.append(ToolMessage(
                        content=result_str, tool_call_id=tool_call_id,
                        name=tool_name,
                    ))
                    continue

                if tool_name == _SUBAGENT_TOOL_NAME:
                    sub_task = str(tool_args.get("task", "") or "").strip()
                    if not sub_task:
                        conversation.append(ToolMessage(
                            content=json.dumps({"error": "empty_task"}),
                            tool_call_id=tool_call_id, name=tool_name,
                        ))
                        continue
                    stok = _start_subagent_async(
                        sub_task, filtered_tools, project_context, bridge,
                    )
                    conversation.append(ToolMessage(
                        content=json.dumps(
                            {
                                "ok": True,
                                "async": True,
                                "token": stok,
                                "hint": (
                                    "Sub-agent (Creator) в фоне. "
                                    f"Вызови get_subagent_result(token='{stok}', wait_seconds=...). "
                                    "Пока можешь вызвать долгий run_command; "
                                    "тест — через get_subagent_result с ожиданием."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                        tool_call_id=tool_call_id, name=tool_name,
                    ))
                    continue

                if tool_name == _GET_SUBAGENT_TOOL_NAME:
                    tok = str(
                        tool_args.get("token", "")
                        or tool_args.get("job_id", "")
                        or "",
                    ).strip()
                    try:
                        w_s = float(tool_args.get("wait_seconds", 0) or 0)
                    except (TypeError, ValueError):
                        w_s = 0.0
                    sub_join = _join_subagent(tok, w_s) if tok else {
                        "ok": False, "error": "token_required",
                    }
                    conversation.append(ToolMessage(
                        content=_render_tool_result(sub_join),
                        tool_call_id=tool_call_id, name=tool_name,
                    ))
                    continue

                if tool_name == _FINAL_DONE_TOOL_NAME:
                    elapsed_run = _DEEP_STATE.elapsed()
                    if (steps < _MIN_STEPS_BEFORE_FINAL
                            or elapsed_run < _MIN_RUNTIME_BEFORE_FINAL_SEC):
                        need_t = max(0, int(_MIN_RUNTIME_BEFORE_FINAL_SEC - elapsed_run))
                        need_s = max(0, _MIN_STEPS_BEFORE_FINAL - steps)
                        conversation.append(ToolMessage(
                            content=json.dumps(
                                {
                                    "ok": False,
                                    "reason": "final_done_blocked_min_session",
                                    "elapsed_sec": int(elapsed_run),
                                    "steps": int(steps),
                                    "need_more_sec": need_t,
                                    "need_more_steps": need_s,
                                    "hint": (
                                        "Преждевременный deep_final_done: продолжи "
                                        "тулами — добавь/запусти тесты, README или "
                                        "docs, прогони сборку/линтер (`npm test`, "
                                        "`pytest`, …), улучши UX и обработку ошибок. "
                                        f"Минимум ещё ~{need_t} с и ~{need_s} шагов "
                                        "с инструментами, затем можно завершить."
                                    ),
                                },
                                ensure_ascii=False,
                            ),
                            tool_call_id=tool_call_id,
                            name=tool_name,
                        ))
                        continue
                    final_report = str(tool_args.get("report", "") or "Готово.")
                    conversation.append(ToolMessage(
                        content=json.dumps({"ok": True}, ensure_ascii=False),
                        tool_call_id=tool_call_id, name=tool_name,
                    ))
                    break

                # Standard tool dispatch.
                tool_obj = tool_map.get(tool_name)
                t_tool_start = time.time()
                if tool_obj is None:
                    result: Any = f"Unknown tool: {tool_name}"
                else:
                    tool_args, val_err = validate_tool_arguments(tool_name, tool_args)
                    if val_err:
                        result = {"error": "argument_validation", "detail": val_err}
                    else:
                        try:
                            result = tool_obj.invoke(tool_args)
                        except Exception as e:
                            result = f"Error: {e}"
                # Stamp elapsed seconds on dict results so every tool card
                # shows a timer (``⏱ 0.42s``). No-op for string results.
                if isinstance(result, dict) and "elapsed_seconds" not in result:
                    result["elapsed_seconds"] = round(time.time() - t_tool_start, 3)

                try:
                    bridge.on_tool_result(tool_name, result)
                except Exception:
                    pass

                facts.extend(_extract_facts(tool_name, result))
                if len(facts) > _MAX_FACTS * 2:
                    facts = facts[-_MAX_FACTS:]

                conversation.append(ToolMessage(
                    content=_render_tool_result(result),
                    tool_call_id=tool_call_id,
                    name=tool_name,
                ))

            if final_report:
                break

            # Auto-checkpoint cadence (in addition to model-driven ones).
            if steps and steps % _CHECKPOINT_EVERY_STEPS == 0 and session_id:
                times = _DEEP_STATE.mark_checkpoint()
                cp_idx = _DEEP_STATE.checkpoint_count
                cp_id = (f"dcp_auto_{session_id or 'anon'}_"
                         f"{int(time.time())}_{cp_idx}")
                turn_idx = (sum(1 for m in messages if isinstance(m, HumanMessage))
                            if messages is not None else 0)
                try:
                    if session_id and messages is not None:
                        save_pre_turn_snapshot(session_id, turn_idx, list(messages))
                        save_pre_turn_workspace_snapshot(session_id, turn_idx)
                except Exception:
                    pass
                register_checkpoint(cp_id, session_id, turn_idx,
                                    f"Auto step {steps}")
                summary_with_time = (
                    "Периодическая контрольная точка Deep-сессии.\n"
                    f"⏱ этап {_format_elapsed(times['since_prev'])}  ·  "
                    f"сессия {_format_elapsed(times['total'])}"
                )
                try:
                    bridge.on_deep_checkpoint(
                        cp_id=cp_id,
                        index=cp_idx,
                        title=f"Автосохранение · шаг {steps}",
                        summary=summary_with_time,
                        turn_index=turn_idx,
                    )
                except Exception:
                    pass
    finally:
        _hb_stop.set()
        _DEEP_STATE.stop()
        if _term_tool is not None:
            _term_tool.AUTO_CONFIRM = prev_auto_confirm
        try:
            if hasattr(bridge, "on_deep_status"):
                bridge.on_deep_status(running=False)
        except Exception:
            pass

    # ── Final summary ──
    total_elapsed = _format_elapsed(_DEEP_STATE.elapsed())
    if not final_report:
        prompt_tail = (
            "СВОДКА. Остановка по запросу пользователя."
            if stopped_by_user else
            "СВОДКА. Достигнут лимит шагов."
        )
        try:
            conversation.append(HumanMessage(
                content=prompt_tail + " Дай короткий итоговый отчёт: что "
                "успел сделать, где какие файлы лежат, что осталось."
            ))
            wrap = llm.invoke(sanitize_messages(conversation))
            final_report = coerce_assistant_content_to_text(
                getattr(wrap, "content", "")
            ).strip() or (
                "Остановлен пользователем." if stopped_by_user
                else "Достигнут лимит шагов."
            )
        except Exception as e:
            final_report = (
                f"Остановлен ({'пользователь' if stopped_by_user else 'лимит'}). "
                f"Сводка недоступна: {e}"
            )

    return (
        f"⏱ Время работы Deep Solver: {total_elapsed}\n\n"
        + final_report
    )


# ─── Sub-agent helper ─────────────────────────────────────────────────

def _run_subagent(sub_task: str, tools: List[BaseTool],
                  project_context: str, bridge: Any) -> Dict[str, Any]:
    """Delegate a heavy subtask to the Creator Mode orchestrator."""
    try:
        try:
            from .creator_mode import run_creator_mode
            from .creator_summary import format_creator_summary_text
        except ImportError:
            from Agent.creator_mode import run_creator_mode
            from Agent.creator_summary import format_creator_summary_text
    except Exception as e:
        return {"ok": False, "error": f"creator_mode unavailable: {e}"}

    try:
        bridge.on_info(f"🧩 Sub-agent: {sub_task[:80]}")
    except Exception:
        pass

    try:
        res = run_creator_mode(task=sub_task, tools=tools,
                               project_context=project_context, depth=1,
                               parent_worker_id="deep")
        return {
            "ok": True,
            "summary": format_creator_summary_text(res),
            "status": res.get("status") if isinstance(res, dict) else None,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Rollback / continue from a checkpoint ────────────────────────────

def apply_checkpoint_action(cp_id: str, action: str,
                            messages: List[Any],
                            enhanced_system_prompt: str,
                            session_id: str,
                            bridge: Any) -> Dict[str, Any]:
    """Execute "rollback" or "continue" for a Deep checkpoint.

    Trims the message list and workspace back to the checkpoint's turn,
    then, when ``action == "continue"``, returns metadata the UI should
    use to mount a chip in the attachment strip so the user can seed the
    next prompt from that exact point.
    """
    entry = get_checkpoint(cp_id)
    if not entry:
        return {"ok": False, "error": "checkpoint_not_found"}

    turn_index = int(entry.get("turn_index") or 0)
    sess = str(entry.get("session_id") or session_id)

    try:
        raw = load_pre_turn_snapshot(sess, turn_index)
        if not raw:
            return {"ok": False, "error": "no_snapshot"}
        restored = messages_from_stored_dicts(raw, enhanced_system_prompt)
        messages.clear()
        messages.extend(restored)
        ws = restore_turn_workspace(sess, turn_index)
        delete_turn_snapshots_from(sess, turn_index)
        delete_turn_workspace_snapshots_from(sess, turn_index)
        save_state(messages, session_id=sess)
        try:
            bridge.on_chat_reload_messages(list(messages))
        except Exception:
            pass
        try:
            bridge.on_file_changed("")
        except Exception:
            pass
        clear_checkpoint(cp_id)
        result: Dict[str, Any] = {
            "ok": True,
            "action": action,
            "turn_index": turn_index,
            "workspace": ws if isinstance(ws, dict) else {},
            "checkpoint_title": str(entry.get("title") or ""),
            "checkpoint_id": cp_id,
        }
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}
