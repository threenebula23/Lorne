"""
Custom Tools — загрузка, управление и регистрация пользовательских инструментов.

Пользователь может создавать Python-файлы с @tool-функциями в ~/.tca_custom_tools/.
Они автоматически загружаются при старте и доступны агенту.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool

# ─── Хранилище ──────────────────────────────────────────────────────
CUSTOM_TOOLS_DIR = Path.home() / ".tca_custom_tools"

_TEMPLATE = '''"""
Custom tool: {name}
"""
from langchain_core.tools import tool


@tool
def {name}(input_text: str) -> str:
    """{description}"""
    # Ваш код здесь
    return f"Результат: {{input_text}}"
'''


def _ensure_dir() -> None:
    """Создаёт директорию для кастомных тулов если её нет."""
    CUSTOM_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    init_file = CUSTOM_TOOLS_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")


def load_custom_tools() -> List[BaseTool]:
    """Сканирует ~/.tca_custom_tools/, загружает все @tool-декорированные функции.

    Returns:
        Список BaseTool-объектов, готовых к использованию агентом.
    """
    _ensure_dir()
    tools: List[BaseTool] = []
    errors: List[str] = []

    for py_file in sorted(CUSTOM_TOOLS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            module_name = f"_custom_tool_{py_file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, str(py_file))
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Извлечь все объекты BaseTool из модуля
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if isinstance(obj, BaseTool):
                    tools.append(obj)
        except Exception as e:
            errors.append(f"{py_file.name}: {e}")

    if errors:
        try:
            from Interface.visualization import print_warning
        except ImportError:
            def print_warning(m: str) -> None:
                print(f"  ⚠ {m}")
        for err in errors:
            print_warning(f"Custom tool ошибка: {err}")

    return tools


def list_custom_tools() -> List[Dict[str, str]]:
    """Возвращает информацию обо всех кастомных тулах.

    Returns:
        [{name, description, file}, ...]
    """
    result: List[Dict[str, str]] = []
    loaded = load_custom_tools()
    for t in loaded:
        result.append({
            "name": getattr(t, "name", "?"),
            "description": (getattr(t, "description", "") or "")[:120],
            "file": getattr(t, "__module__", ""),
        })

    # Также показать файлы, которые не загрузились
    _ensure_dir()
    loaded_names = {r["name"] for r in result}
    for py_file in sorted(CUSTOM_TOOLS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        stem = py_file.stem
        if stem not in loaded_names:
            result.append({
                "name": stem,
                "description": "(ошибка загрузки)",
                "file": py_file.name,
            })

    return result


def add_custom_tool(name: str, code: Optional[str] = None, description: str = "Custom tool") -> Dict[str, Any]:
    """Сохраняет кастомный тул как .py файл.

    Args:
        name: Имя тула (будет использовано как имя файла без .py)
        code: Python-код с @tool декоратором. Если None — создаётся шаблон.
        description: Описание (для шаблона)

    Returns:
        {"ok": True, "path": str} или {"ok": False, "error": str}
    """
    _ensure_dir()
    # Очистить имя
    safe_name = "".join(c for c in name if c.isalnum() or c == "_").strip("_")
    if not safe_name:
        return {"ok": False, "error": "Некорректное имя тула"}

    filepath = CUSTOM_TOOLS_DIR / f"{safe_name}.py"

    if code is None:
        code = _TEMPLATE.format(name=safe_name, description=description)

    try:
        filepath.write_text(code, encoding="utf-8")
        # Валидация: попробовать загрузить
        test_tools = []
        try:
            module_name = f"_custom_tool_test_{safe_name}"
            spec = importlib.util.spec_from_file_location(module_name, str(filepath))
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for attr_name in dir(module):
                    obj = getattr(module, attr_name)
                    if isinstance(obj, BaseTool):
                        test_tools.append(getattr(obj, "name", "?"))
                # Cleanup
                if module_name in sys.modules:
                    del sys.modules[module_name]
        except Exception as e:
            return {"ok": True, "path": str(filepath), "warning": f"Файл создан, но есть ошибка: {e}"}

        return {
            "ok": True,
            "path": str(filepath),
            "tools_found": test_tools,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def remove_custom_tool(name: str) -> Dict[str, Any]:
    """Удаляет кастомный тул.

    Args:
        name: Имя тула (без .py)

    Returns:
        {"ok": True} или {"ok": False, "error": str}
    """
    _ensure_dir()
    safe_name = "".join(c for c in name if c.isalnum() or c == "_").strip("_")
    filepath = CUSTOM_TOOLS_DIR / f"{safe_name}.py"

    if not filepath.exists():
        return {"ok": False, "error": f"Тул '{safe_name}' не найден в {CUSTOM_TOOLS_DIR}"}

    try:
        filepath.unlink()
        # Удалить из sys.modules если был загружен
        mod_name = f"_custom_tool_{safe_name}"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        return {"ok": True, "removed": safe_name}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_custom_tools_prompt() -> str:
    """Формирует блок для system prompt с описанием кастомных тулов.

    Returns:
        Строка с описанием, или пустая строка если тулов нет.
    """
    items = list_custom_tools()
    if not items:
        return ""

    lines = [
        "\n## CUSTOM TOOLS (пользовательские инструменты)",
        "Следующие инструменты добавлены пользователем и доступны для использования:",
        "",
    ]
    for item in items:
        lines.append(f"- **{item['name']}** — {item['description']}")

    lines.append("")
    lines.append("Используй их когда задача подходит под их описание.")
    return "\n".join(lines)


def reload_custom_tools() -> List[BaseTool]:
    """Перезагрузить все кастомные тулы (очистить кэш модулей и загрузить заново)."""
    # Очистить загруженные модули
    to_remove = [k for k in sys.modules if k.startswith("_custom_tool_")]
    for k in to_remove:
        del sys.modules[k]
    return load_custom_tools()
