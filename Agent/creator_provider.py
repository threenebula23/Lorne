"""
Creator Provider — маршрутизация между локальной и тяжёлой моделью.

Определяет сложность задачи и направляет на подходящую модель:
- Простые задачи → локальная модель (qwen3.5:27b на OPENAI_API_BASE)
- Сложные задачи → тяжёлая модель через OpenRouter
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, Tuple

from langchain_openai import ChatOpenAI

try:
    from .llm_provider import get_llm, load_config, save_config, _env
except ImportError:
    from Agent.llm_provider import get_llm, load_config, save_config, _env


# ─── Конфигурация Creator Mode ─────────────────────────────────────

DEFAULT_LOCAL_BASE_URL = "http://192.168.1.20:3000/api"
DEFAULT_LOCAL_MODEL = "qwen3.5:27b"
DEFAULT_MAX_WORKERS = 4


def get_creator_config() -> Dict[str, Any]:
    """Загрузить конфигурацию creator mode."""
    cfg = load_config()
    creator = cfg.get("creator", {})
    orch = str(creator.get("orchestration", "parallel") or "parallel").lower().strip()
    if orch not in ("parallel", "sequential", "supervisor", "hierarchical"):
        orch = "parallel"
    return {
        "local_base_url": creator.get("local_base_url", _env("OPENAI_API_BASE", DEFAULT_LOCAL_BASE_URL)),
        "local_model": creator.get("local_model", DEFAULT_LOCAL_MODEL),
        "max_workers": creator.get("max_workers", DEFAULT_MAX_WORKERS),
        "enabled": creator.get("enabled", False),
        "orchestration": orch,
    }


def save_creator_config(updates: Dict[str, Any]) -> None:
    """Сохранить настройки creator mode."""
    cfg = load_config()
    creator = cfg.get("creator", {})
    creator.update(updates)
    save_config({"creator": creator})


# ─── LLM создание ──────────────────────────────────────────────────

def _resolve_local_api_key() -> str:
    """Определить API ключ для локального сервера.

    Приоритет:
    1. LOCAL_API_KEY — отдельный ключ для локального сервера
    2. OPENROUTER_API_KEY — fallback (OpenWebUI часто использует такой же формат)
    3. 'not-needed' — для серверов не требующих аутентификации (LM Studio, Ollama)
    """
    local_key = _env("LOCAL_API_KEY", "")
    if local_key:
        return local_key
    openrouter_key = _env("OPENROUTER_API_KEY", "")
    if openrouter_key:
        return openrouter_key
    return "not-needed"


def _resolve_local_base_url(base_url: str) -> str:
    """Нормализовать base URL для OpenAI-совместимого API.

    Убирает trailing slash, и если URL не заканчивается на /v1,
    пробует добавить /v1 (стандарт для OpenAI-совместимых серверов).
    """
    url = base_url.rstrip("/")
    # Если уже заканчивается на /v1 — оставить как есть
    if url.endswith("/v1"):
        return url
    return url


def get_local_llm(
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 8192,
) -> ChatOpenAI:
    """Создаёт ChatOpenAI подключённый к локальному серверу.

    Args:
        model_name: Имя модели (по умолчанию из конфига)
        base_url: URL локального API (по умолчанию из OPENAI_API_BASE или конфига)
        temperature: Температура генерации
        max_tokens: Максимум токенов ответа

    Returns:
        ChatOpenAI инстанс для локальной модели
    """
    config = get_creator_config()
    if model_name is None:
        model_name = config["local_model"]
    if base_url is None:
        base_url = config["local_base_url"]

    resolved_url = _resolve_local_base_url(base_url)
    api_key = _resolve_local_api_key()

    return ChatOpenAI(
        base_url=resolved_url,
        api_key=api_key,
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        request_timeout=180,  # Локальные модели могут быть медленнее
        max_retries=2,
    )


def get_heavy_llm() -> Tuple[ChatOpenAI, str]:
    """Создаёт ChatOpenAI через OpenRouter (тяжёлая модель).

    Returns:
        (ChatOpenAI, model_name)
    """
    llm, _, model_name = get_llm("quality")
    return llm, model_name


def check_local_server(base_url: Optional[str] = None) -> bool:
    """Проверить доступность локального сервера (включая аутентификацию).

    Returns:
        True если сервер отвечает и аутентификация проходит
    """
    import urllib.request
    import urllib.error

    config = get_creator_config()
    url = (base_url or config["local_base_url"]).rstrip("/")
    api_key = _resolve_local_api_key()

    # Попробовать OpenAI-совместимые эндпоинты
    endpoints = [
        f"{url}/v1/models",
        f"{url}/models",
    ]
    # Если URL уже содержит /v1, попробовать /models напрямую
    if url.endswith("/v1"):
        endpoints = [f"{url}/models"] + endpoints

    for endpoint in endpoints:
        try:
            req = urllib.request.Request(endpoint, method="GET")
            req.add_header("Content-Type", "application/json")
            if api_key and api_key != "not-needed":
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except urllib.error.HTTPError as e:
            if e.code == 401 or e.code == 403:
                # Сервер доступен, но аутентификация не прошла
                return False
            continue
        except Exception:
            continue

    return False


# ─── Классификация сложности задачи ────────────────────────────────

_COMPLEX_PATTERNS = [
    r"рефактор",
    r"архитектур",
    r"миграци",
    r"несколько файлов",
    r"много файлов",
    r"перепиши\s+вс[её]",
    r"complex",
    r"refactor",
    r"architect",
    r"migration",
    r"multiple\s+files",
    r"rewrite\s+entire",
    r"оптимиз",
    r"весь\s+проект",
    r"все\s+файлы",
    r"безопасност",
    r"security",
    r"database\s+schema",
    r"API\s+design",
]

_SIMPLE_PATTERNS = [
    r"создай\s+файл",
    r"напиши\s+функцию",
    r"добав[ьи]",
    r"исправ[ьи]",
    r"поменяй",
    r"покажи",
    r"прочитай",
    r"create\s+file",
    r"write\s+function",
    r"add\s+",
    r"fix\s+",
    r"show\s+",
    r"read\s+",
    r"simple",
    r"один\s+файл",
    r"single\s+file",
]


def classify_task_complexity(task_text: str, plan_steps: int = 0) -> str:
    """Определить сложность задачи.

    Args:
        task_text: Текст задачи
        plan_steps: Количество шагов в плане (если известно)

    Returns:
        "simple" или "complex"
    """
    text = (task_text or "").lower()

    # Эвристики на основе плана
    if plan_steps > 6:
        return "complex"

    # Длина текста
    word_count = len(text.split())
    if word_count > 100:
        return "complex"

    # Паттерны сложности
    complex_score = sum(1 for p in _COMPLEX_PATTERNS if re.search(p, text))
    simple_score = sum(1 for p in _SIMPLE_PATTERNS if re.search(p, text))

    if complex_score >= 2:
        return "complex"
    if complex_score > simple_score and word_count > 30:
        return "complex"

    return "simple"


def route_to_model(
    task_text: str,
    plan_steps: int = 0,
    local_model: Optional[str] = None,
    local_base_url: Optional[str] = None,
) -> Tuple[ChatOpenAI, str, str]:
    """Маршрутизировать задачу на подходящую модель.

    Returns:
        (llm, model_name, model_type) — model_type: "local" или "heavy"
    """
    complexity = classify_task_complexity(task_text, plan_steps)

    if complexity == "simple":
        # Попробовать локальную модель
        config = get_creator_config()
        model = local_model or config["local_model"]
        base = local_base_url or config["local_base_url"]

        try:
            llm = get_local_llm(model_name=model, base_url=base)
            return llm, model, "local"
        except Exception:
            # Fallback на тяжёлую если локальная недоступна
            llm, model_name = get_heavy_llm()
            return llm, model_name, "heavy"
    else:
        llm, model_name = get_heavy_llm()
        return llm, model_name, "heavy"
