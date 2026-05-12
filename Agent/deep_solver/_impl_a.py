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

try:
    from ..runtime_paths import env_pref
except ImportError:
    from Agent.runtime_paths import env_pref

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
        safe_chat_invoke_with_tool_recovery,
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
        safe_chat_invoke_with_tool_recovery,
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

# ``LORNE_DEEP_MAX_STEPS`` / ``TCA_DEEP_MAX_STEPS``: max tool rounds (``0`` / empty / ``unlimited`` / ``inf`` = практически без лимита).
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
# Override for tiny tasks: ``LORNE_DEEP_MIN_RUNTIME_SEC=0 LORNE_DEEP_MIN_STEPS=0`` (или ``TCA_*``).
_MIN_RUNTIME_BEFORE_FINAL_SEC = max(
    0, int(env_pref("DEEP_MIN_RUNTIME_SEC", str(20 * 60)))
)
_MIN_STEPS_BEFORE_FINAL = max(
    0, int(env_pref("DEEP_MIN_STEPS", "40"))
)


def _resolve_max_tool_rounds() -> int:
    raw = (env_pref("DEEP_MAX_STEPS", "") or "").strip().lower()
    if raw in ("", "0", "unlimited", "inf", "infinity", "none"):
        return 2**31 - 1
    try:
        return max(1, int(raw))
    except Exception:
        return 2**31 - 1


def _deep_exit_only_on_user_stop() -> bool:
    """If True (default), ``deep_final_done`` does not end the loop; only user stop does."""
    v = (env_pref("DEEP_EXIT_ONLY_ON_USER_STOP", "1") or "1").strip().lower()
    return v in ("1", "true", "yes", "on")


def _rule3_block() -> str:
    if _deep_exit_only_on_user_stop():
        return (
            "3. **Сам выставляй подцели.** После каждой выполненной подзадачи задай\n"
            "   следующий маленький шаг в сторону главной цели. Не пиши «готово,\n"
            "   жду» — сессия идёт, пока пользователь не остановит её (кнопка «Стоп» или `/stop`)."
        )
    return (
        "3. **Сам выставляй подцели.** После каждой выполненной подзадачи задай\n"
        "   следующий маленький шаг в сторону главной цели. Не пиши «готово,\n"
        "   жду», пока `deep_final_done` не вызван."
    )


def _rule9_block() -> str:
    if _deep_exit_only_on_user_stop():
        return (
            "9. **Сессия и `deep_final_done`.** Останов **только** по запросу пользователя "
            "(кнопка «Стоп», `/stop`). Вызов `deep_final_done` **не** завершает цикл: в `report` "
            "кратко подведи итог, затем продолжай тулами; **какую** работу брать дальше — "
            "см. правило 10 (самопостановка **в рамках** главной цели). Пороги по времени/шагам "
            "отсекают преждевременный «пустой» отчёт, но сессия не завершится, пока пользователь "
            "сам не остановит её."
        )
    return (
        "9. **Завершение сессии (`deep_final_done`).** Вызывай **только** когда\n"
        "   одновременно: (а) прошло не меньше ~20 минут активной работы,\n"
        "   (б) выполнено много шагов с тулами, (в) ты реально прогнал проверки\n"
        "   качества: тесты, README/доки, сборка или линтер, просмотрел критичные\n"
        "   файлы. До этого момента **запрещено** закрывать сессию одним отчётом\n"
        "   «всё создано» — после MVP продолжай улучшать, пока не исчерпан смысл\n"
        "   или пользователь не нажал «Стоп»."
    )


def _rule10_block() -> str:
    """How to self-assign the next subtask when the model 'wants to stop' (user-stop mode)."""
    if not _deep_exit_only_on_user_stop():
        return ""
    return (
        "\n10. **Когда тянет «закончить» / кажется, что сделано всё важное.** "
        "Ты **не** меняешь и не отменяешь главную цель сверху. Если хочется "
        "остановиться, всё равно **сам сформулируй ровно одну** следующую "
        "конкретную подзадачу, которая: (а) **напрямую вытекает** из «Главной цели» "
        "(тот же продукт, тот же scope); (б) **усиливает** результат: тест, док, "
        "обработка ошибок, граничный случай, согласованность UI, рефактор **в границах** "
        "той цели. Запрещено: придумать **новую** тему «чтобы продолжить сессию», "
        "уехать в несвязанный фич-реквест, другой стек, «учебный» пример. "
        "Если сомнение, сверься с «Жёсткими правилами фокуса»; при срыве в сторону — "
        "`deep_checkpoint` с title «сверка с главной целью» и возврат к тому, что "
        "ещё не закрыто по **этой** формулировке цели."
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
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


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


def list_checkpoints() -> List[Dict[str, Any]]:
    """Return all live deep checkpoints (newest first)."""
    with _DEEP_CHECKPOINT_LOCK:
        rows: List[Dict[str, Any]] = []
        for cp_id, data in _DEEP_CHECKPOINT_INDEX.items():
            row = {"id": cp_id}
            if isinstance(data, dict):
                row.update(data)
            rows.append(row)
    rows.sort(key=lambda x: float(x.get("ts") or 0.0), reverse=True)
    return rows


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
{rule_3_block}
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
{rule_9_block}{rule_10_block}

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
        """Итог по текущему этапу: что сделано и где (5–15 строк в ``report``).

        Если в настройках сессия **не** завершается по этому вызову, после
        ``report`` **продолжи работу**: сам сформулируй **один** следующий шаг
        строго в рамке **той же главной цели** (тест, док, полировка, баг) —
        без новых несвязанных тем; см. системный промпт, правила 3 и 10.
        """
        return f"deep_done: {report[:120]}"

    return [deep_checkpoint, spawn_subagent, get_subagent_result, deep_final_done]


