"""Интерактивные инструменты: запрос ввода у пользователя в терминале."""
from typing import Any, Dict

from langchain_core.tools import tool


@tool
def ask_user(question: str) -> Dict[str, Any]:
    """Спросить пользователя в терминале. Выводит question и возвращает ответ пользователя. Используй для подтверждения действий (например, запуск команды), выбора варианта или уточнения."""
    try:
        reply = input(f"  {question}\n  > ").strip()
        return {"question": question, "reply": reply, "ok": True}
    except (EOFError, KeyboardInterrupt):
        return {"question": question, "reply": "", "ok": False}
