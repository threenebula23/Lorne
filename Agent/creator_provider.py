"""
Creator Provider — маршрутизация между локальной и тяжёлой моделью.

Определяет сложность задачи и направляет на подходящую модель:
- Простые задачи → локальная модель (qwen3.5:27b на OPENAI_API_BASE)
- Сложные задачи → тяжёлая модель через OpenRouter
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_openai import ChatOpenAI

try:
    from .llm_provider import (
        get_llm, load_config, save_config, _env,
        _resolve_ollama_settings, _build_ollama_chat_llm, _build_ollama_openai_llm,
        _HAS_CHAT_OLLAMA,
    )
except ImportError:
    from Agent.llm_provider import (
        get_llm, load_config, save_config, _env,
        _resolve_ollama_settings, _build_ollama_chat_llm, _build_ollama_openai_llm,
        _HAS_CHAT_OLLAMA,
    )


# ─── Конфигурация Creator Mode ─────────────────────────────────────

DEFAULT_LOCAL_BASE_URL = "http://192.168.1.20:3000/api"
DEFAULT_LOCAL_MODEL = "qwen3.5:27b"
DEFAULT_MAX_WORKERS = 4


def get_creator_config() -> Dict[str, Any]:
    """Загрузить конфигурацию creator mode.

    UI-level настройки (orchestration / max_workers) имеют приоритет над project
    config, чтобы пользователь мог менять их из экрана Settings → Agents без
    перезапуска приложения. Это работает одинаково для локальных и удалённых
    моделей — creator читает один и тот же блок.
    """
    cfg = load_config()
    creator = cfg.get("creator", {})
    orch = str(creator.get("orchestration", "parallel") or "parallel").lower().strip()
    max_workers = int(creator.get("max_workers", DEFAULT_MAX_WORKERS) or DEFAULT_MAX_WORKERS)

    # Override with UI prefs when available.
    try:
        from Interface.ui_prefs import load_prefs
        prefs = load_prefs()
        ui_orch = str(prefs.get("orchestration_mode", "") or "").lower().strip()
        mode_map = {"parallel": "parallel", "pipeline": "sequential", "auto": orch}
        if ui_orch in mode_map:
            orch = mode_map[ui_orch]
        ui_workers = int(prefs.get("orchestration_max_workers", 0) or 0)
        if ui_workers > 0:
            max_workers = ui_workers
    except Exception:
        pass

    if orch not in ("parallel", "sequential", "supervisor", "hierarchical"):
        orch = "parallel"
    return {
        "local_base_url": creator.get("local_base_url", _env("OPENAI_API_BASE", DEFAULT_LOCAL_BASE_URL)),
        "local_model": creator.get("local_model", DEFAULT_LOCAL_MODEL),
        "max_workers": max_workers,
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
    # Уже нормализованный OpenAI/OpenWebUI путь.
    if url.endswith("/v1") or url.endswith("/api") or url.endswith("/api/v1"):
        return url
    # Ollama / LM Studio обычно дают базу без /v1.
    return url + "/v1"


def _looks_like_ollama_url(url: str) -> bool:
    """Heuristic: true when the URL looks like a bare Ollama daemon
    (default port 11434, or no `/api`/OpenWebUI suffix)."""
    low = (url or "").strip().lower().rstrip("/")
    if not low:
        return False
    if ":11434" in low:
        return True
    if low.endswith("/api") or low.endswith("/api/v1"):
        # OpenWebUI / vLLM / LM Studio-compat — use OpenAI /v1 transport.
        return False
    # Ends with /v1 or bare host: could still be Ollama /v1 compat.
    # Treat as Ollama when default-looking (localhost / LAN IP on 11434 only).
    return False


def get_local_llm(
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 8192,
) -> Any:
    """Создаёт LLM для локального сервера.

    Автоматически выбирает транспорт:
    - native Ollama через ChatOllama (`/api/chat`), когда URL похож на Ollama
      daemon (порт 11434) и `langchain-ollama` доступен — это даёт правильную
      обработку tool-calls и честное применение `num_ctx`/`top_k`/`repeat_penalty`.
    - OpenAI-compat `ChatOpenAI` во всех остальных случаях (OpenWebUI, LM Studio,
      vLLM, любые custom /v1 эндпоинты).

    Args:
        model_name: Имя модели (по умолчанию из конфига)
        base_url: URL локального API (по умолчанию из OPENAI_API_BASE или конфига)
        temperature: Температура генерации
        max_tokens: Максимум токенов ответа

    Returns:
        ChatOllama или ChatOpenAI инстанс, подключённый к локальному серверу.
    """
    config = get_creator_config()
    if model_name is None:
        model_name = config["local_model"]
    if base_url is None:
        base_url = config["local_base_url"]

    wire_name = str(model_name).split("/", 1)[1] if str(model_name).startswith("ollama/") else str(model_name)

    if _HAS_CHAT_OLLAMA and _looks_like_ollama_url(base_url):
        try:
            import os as _os
            prev = _os.environ.get("OLLAMA_BASE_URL")
            _os.environ["OLLAMA_BASE_URL"] = base_url
            try:
                settings = _resolve_ollama_settings(wire_name, temperature, max_tokens)
                return _build_ollama_chat_llm(wire_name, settings)
            finally:
                if prev is None:
                    _os.environ.pop("OLLAMA_BASE_URL", None)
                else:
                    _os.environ["OLLAMA_BASE_URL"] = prev
        except Exception:
            # Fall through to ChatOpenAI as safety net.
            pass

    resolved_url = _resolve_local_base_url(base_url)
    api_key = _resolve_local_api_key()

    return ChatOpenAI(
        base_url=resolved_url,
        api_key=api_key,
        model=wire_name,
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

    Пробует разные варианты API в порядке популярности:
      • OpenAI-совместимые: ``/v1/models``, ``/models``.
      • Ollama native: ``/api/tags``, ``/api/version``.
      • OpenWebUI: ``/api/models`` (когда base_url уже оканчивается на ``/api``,
        это превращается просто в ``/models``, но мы его и так проверим).
    Также дополнительно дергаем «родительскую» версию без последнего сегмента,
    чтобы URL вида ``.../api`` или ``.../v1`` не оставался «недоступным», если
    сервер отвечает 200 на ``http://host:3000/``.

    Returns:
        True если какой-то эндпоинт ответил 200 / 404 (значит хост есть).
        False только если все попытки вернули соединение-refused / timeout
        или 401/403 (аутентификация).
    """
    import urllib.request
    import urllib.error

    config = get_creator_config()
    url = (base_url or config["local_base_url"]).rstrip("/")
    api_key = _resolve_local_api_key()

    # Нормализуем несколько полезных корней: исходный, без /v1, без /api.
    roots = {url}
    for suffix in ("/v1", "/api", "/v1/chat/completions", "/api/chat/completions"):
        if url.endswith(suffix):
            roots.add(url[: -len(suffix)].rstrip("/"))

    candidates: List[str] = []
    for root in roots:
        if not root:
            continue
        candidates.extend([
            f"{root}/v1/models",        # OpenAI-compat (LM Studio, vLLM, OpenWebUI)
            f"{root}/models",           # некоторые прокси
            f"{root}/api/models",       # OpenWebUI
            f"{root}/api/tags",         # Ollama native
            f"{root}/api/version",      # Ollama native (иногда единственное без auth)
            f"{root}/",                 # base index — последний шанс
        ])
    # Убираем дубли, сохраняя порядок.
    seen: set[str] = set()
    endpoints = [e for e in candidates if not (e in seen or seen.add(e))]

    had_auth_failure = False
    for endpoint in endpoints:
        try:
            req = urllib.request.Request(endpoint, method="GET")
            req.add_header("Content-Type", "application/json")
            if api_key and api_key != "not-needed":
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if 200 <= resp.status < 500:
                    return True
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                had_auth_failure = True
                continue
            # 404/405 и пр. значат, что хост отвечает — сервер жив.
            if 400 <= e.code < 500:
                return True
            continue
        except Exception:
            continue

    # Сервер хоть раз ответил 401/403 — хост есть, просто нет ключа. Для
    # Deep-режима это не фатально (LLM всё равно попытается со своим
    # ключом/без него), поэтому возвращаем True, чтобы не блокировать запуск.
    if had_auth_failure:
        return True

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
