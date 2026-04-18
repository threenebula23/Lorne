"""Режимы оркестрации Creator Mode (мультиагентность: параллель, конвейер, супервайзер, иерархия).

Вдохновлено типичными схемами LangGraph / multi-agent: независимые воркеры, конвейер с передачей
контекста, финальная сводка «супервайзером», выделенная роль ведущего при иерархии.
"""
from __future__ import annotations

from typing import Any, Dict, List

ORCHESTRATION_MODES = ("parallel", "sequential", "supervisor", "hierarchical")


def normalize_orchestration(value: str) -> str:
    v = (value or "parallel").lower().strip()
    return v if v in ORCHESTRATION_MODES else "parallel"


def worker_roles_for_count(n: int, orchestration: str) -> List[str]:
    """Короткие роли для промпта воркера (смена «шляп» как в мультиагентных пайплайнах)."""
    if n <= 0:
        return []
    if orchestration == "hierarchical":
        return ["lead"] + [f"specialist_{i}" for i in range(1, n)]
    pool = ("implementer", "reviewer", "researcher", "integrator", "tester", "documenter")
    return [pool[i % len(pool)] for i in range(n)]


_ROLE_HINTS: Dict[str, str] = {
    "lead": "Ты ведущий воркер: держи цель всей задачи, при необходимости делегируй через spawn_sub_creator.",
    "specialist_1": "Специалист: сфокусируйся на своей подзадаче, учитывая общую цель.",
    "implementer": "Реализуй изменения в коде/файлах по подзадаче.",
    "reviewer": "Проверь согласованность, краевые случаи и качество относительно подзадачи.",
    "researcher": "Собери факты (документация, web, RAG) релевантные подзадаче.",
    "integrator": "Сведи части решения в цельный результат по подзадаче.",
    "tester": "Продумай/запусти проверки (тесты, команды) для подзадачи.",
    "documenter": "Оформи вывод: README, комментарии, отчёт по подзадаче.",
}


def role_hint(role: str) -> str:
    if role in _ROLE_HINTS:
        return _ROLE_HINTS[role]
    if role.startswith("specialist_"):
        return _ROLE_HINTS["specialist_1"]
    return "Выполни свою подзадачу автономно и лаконично."


def format_worker_mode_section(worker_id: str, role: str, orchestration: str) -> str:
    """Блок для SystemMessage после SYSTEM_PROMPT и project_context."""
    orch_line = {
        "parallel": "Оркестрация: параллельно с другими воркерами; не жди их результатов.",
        "sequential": "Оркестрация: конвейер — в user-сообщении может быть контекст предыдущих воркеров.",
        "supervisor": "Оркестрация: параллельная фаза; после всех воркеров супервайзер соберёт сводку.",
        "hierarchical": "Оркестрация: иерархия — ведущий координирует, специалисты закрывают части.",
    }.get(orchestration, "")
    rh = role_hint(role)
    return f"""=== РЕЖИМ ВОРКЕРА (Creator Mode) ===
ID воркера: {worker_id}
Роль: {role}
{rh}
{orch_line}
Выполни ОДНУ конкретную подзадачу. Не задавай лишних вопросов пользователю.
После завершения дай краткий отчёт, что сделано.
"""


def build_worker_user_content(task: str, peer_memo: str) -> str:
    parts: List[str] = []
    if (peer_memo or "").strip():
        parts.append(
            "### Контекст от предыдущих воркеров (уже сделано в этой сессии Creator)\n"
            + peer_memo.strip(),
        )
    parts.append(f"Подзадача:\n{task}\n\nВыполни её.")
    return "\n\n".join(parts)


def synthesize_supervisor_report(task: str, results: List[Dict[str, Any]], llm: Any) -> str:
    """Один проход тяжёлой модели: единый отчёт по всем воркерам."""
    from langchain_core.messages import HumanMessage

    chunks: List[str] = []
    for r in results:
        wid = r.get("worker_id", "?")
        st = r.get("status", "?")
        body = (r.get("result") or "").strip()
        if len(body) > 12000:
            body = body[:11900] + "\n…[усечено для сводки]…\n" + body[-800:]
        chunks.append(f"### {wid} ({st})\n{body}")
    joined = "\n\n".join(chunks)
    if len(joined) > 100_000:
        joined = joined[:99_500] + "\n…"
    prompt = (
        "Ты супервайзер. По результатам воркеров ниже напиши единый связный отчёт на русском:\n"
        "- что сделано в целом по исходной задаче;\n"
        "- что осталось / риски;\n"
        "- рекомендованные следующие шаги.\n\n"
        f"Исходная задача:\n{task}\n\nВыводы воркеров:\n{joined}"
    )
    try:
        msg = llm.invoke([HumanMessage(content=prompt)])
        return str(getattr(msg, "content", "") or "").strip()
    except Exception as e:
        return f"[Супервайзер: ошибка сводки] {e}"
