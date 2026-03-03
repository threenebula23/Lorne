"""
Простая реализация multiagent: логические "под-агенты" (чаты) поверх одной модели.

Это не параллельное выполнение, а способ иметь несколько потоков работы
с разными задачами внутри одного проекта.
"""

from typing import Dict, List


_AGENTS: Dict[str, Dict[str, str]] = {}
_CURRENT_AGENT_ID: str = "default"


def create_agent(agent_id: str, title: str = "") -> str:
    """Создаёт или переинициализирует под-агента с заданным id."""
    global _CURRENT_AGENT_ID
    aid = agent_id.strip() or "default"
    _AGENTS[aid] = {"id": aid, "title": title or aid}
    _CURRENT_AGENT_ID = aid
    return aid


def list_agents() -> List[Dict[str, str]]:
    """Возвращает список известных под-агентов."""
    if not _AGENTS:
        create_agent("default", "Основной поток")
    return list(_AGENTS.values())


def set_current_agent(agent_id: str) -> str:
    """Делает указанного под-агента текущим (если он существует)."""
    global _CURRENT_AGENT_ID
    aid = agent_id.strip() or "default"
    if aid not in _AGENTS:
        create_agent(aid, aid)
    _CURRENT_AGENT_ID = aid
    return aid


def get_current_agent() -> str:
    """Возвращает id текущего под-агента."""
    if not _AGENTS:
        create_agent("default", "Основной поток")
    return _CURRENT_AGENT_ID


def get_agent_count() -> int:
    """Возвращает текущее число логических под-агентов."""
    if not _AGENTS:
        create_agent("default", "Основной поток")
    return len(_AGENTS)

