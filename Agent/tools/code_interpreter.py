"""Code Interpreter tool for TCA agent.
Allows the agent to execute Python code and see the output.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from typing import Any, Dict
from langchain_core.tools import tool


@tool
def code_interpreter(code: str, timeout: int = 30) -> Dict[str, Any]:
    """Выполняет произвольный Python-код и возвращает stdout/stderr.
    Используй для вычислений, обработки данных, проверки алгоритмов.
    Код запускается в отдельном процессе; stdin закрыт — input() даст EOF, не ожидай интерактивного ввода.
    Доступны стандартные библиотеки.
    """
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout expired after {timeout} seconds"}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}
    finally:
        import os
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
