"""Интерактивные инструменты: запрос ввода у пользователя в терминале."""
from typing import Any, Dict

from langchain_core.tools import tool


@tool
def ask_user(question: str) -> Dict[str, Any]:
    """Спросить пользователя в терминале. Выводит question и возвращает ответ пользователя. Используй для подтверждения действий (например, запуск команды), выбора варианта или уточнения."""
    import sys
    if not sys.stdin.isatty():
        return {
            "question": question, 
            "reply": "Terminal input unavailable (EOF or not a TTY). DO NOT RETRY THIS TOOL. Please proceed with alternative steps.", 
            "ok": False
        }
    
    try:
        reply = input(f"  {question}\n  > ").strip()
        return {"question": question, "reply": reply, "ok": True}
    except (EOFError, KeyboardInterrupt, RuntimeError):
        return {
            "question": question, 
            "reply": "Terminal input unavailable (EOF/Interrupt). DO NOT RETRY THIS TOOL. Please proceed with alternative steps.", 
            "ok": False
        }
