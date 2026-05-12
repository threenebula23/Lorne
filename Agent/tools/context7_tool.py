"""Инструмент Context7 — прямой вызов REST API.

Использует ``https://context7.com/api/v2``. Без ``CONTEXT7_API_KEY`` возможен
fallback на поиск. Ключ: регистрация на https://context7.com/dashboard .
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

_C7_BASE = "https://context7.com/api/v2"
_CACHE: Dict[str, Any] = {}


def _c7_api_key() -> str:
    return os.getenv("CONTEXT7_API_KEY", "").strip()


def _c7_request(endpoint: str, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Make a request to Context7 API."""
    key = _c7_api_key()
    if not key:
        return None

    query_string = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    url = f"{_C7_BASE}/{endpoint}?{query_string}"

    cache_key = url
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    try:
        from Interface.branding import user_agent_fragment
        _ua = user_agent_fragment()
    except ImportError:
        _ua = "Lorne/0.98"
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": _ua,
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            _CACHE[cache_key] = data
            return data
    except Exception:
        return None


def _ddgs_fallback(query: str, library: str = "", max_results: int = 3) -> Dict[str, Any]:
    """Fallback to DuckDuckGo search."""
    try:
        from ddgs import DDGS
    except ImportError:
        return {"error": "ddgs не установлен, CONTEXT7_API_KEY не задан"}

    search_query = f"{query} documentation"
    if library:
        search_query = f"{library} {query} documentation"

    try:
        results = DDGS().text(search_query, max_results=max_results)
        return {
            "source": "ddgs_fallback",
            "query": query,
            "library": library,
            "results": [
                {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
                for r in results
            ],
            "hint": "Установи CONTEXT7_API_KEY для лучших результатов (бесплатно: context7.com/dashboard)",
        }
    except Exception as e:
        return {"error": str(e)}


@tool
def resolve_library(library_name: str) -> Dict[str, Any]:
    """Найти библиотеку в Context7 по имени. Возвращает Context7 ID для использования в get_library_docs.
    Примеры: 'react', 'fastapi', 'langchain', 'nextjs'."""
    data = _c7_request("libs/search", {"query": library_name})
    if data is None:
        return _ddgs_fallback(library_name, library_name)

    results = data if isinstance(data, list) else data.get("results", [])
    formatted = []
    for r in results[:5]:
        formatted.append({
            "id": r.get("id", ""),
            "title": r.get("title", ""),
            "description": r.get("description", "")[:200],
            "snippets": r.get("codeSnippetsCount", 0),
            "trust_score": r.get("trustScore", 0),
        })

    return {
        "source": "context7",
        "query": library_name,
        "results": formatted,
        "usage": "Используй ID из результатов с get_library_docs(library_id=..., query=...)",
    }


@tool
def get_library_docs(library_id: str, query: str, max_tokens: int = 5000) -> Dict[str, Any]:
    """Получить документацию библиотеки из Context7.
    library_id — ID из resolve_library (например '/reactjs/react.dev').
    query — что именно нужно найти (например 'hooks useState useEffect').
    max_tokens — максимальное число токенов в ответе."""
    params = {
        "libraryId": library_id,
        "query": query,
    }
    if max_tokens:
        params["tokens"] = str(max_tokens)

    data = _c7_request("context", params)
    if data is None:
        return _ddgs_fallback(query, library_id.split("/")[-1] if "/" in library_id else library_id)

    context_text = data.get("context", "")
    sources = data.get("sources", [])

    formatted_sources = []
    for s in sources[:10]:
        formatted_sources.append({
            "title": s.get("title", ""),
            "url": s.get("url", ""),
            "segment": s.get("segment", "")[:200],
        })

    return {
        "source": "context7",
        "library_id": library_id,
        "query": query,
        "context": context_text[:max_tokens * 4] if context_text else "Документация не найдена",
        "sources": formatted_sources,
        "tokens_used": len(context_text.split()),
    }


@tool
def get_documentation(query: str, library: str = "") -> Dict[str, Any]:
    """Ищет документацию для библиотек и фреймворков.
    Если установлен CONTEXT7_API_KEY — использует Context7 API для точных результатов.
    Иначе — DuckDuckGo поиск.
    query — текст запроса, library — название библиотеки (опционально)."""
    if _c7_api_key() and library:
        resolve_result = _c7_request("libs/search", {"query": library})
        if resolve_result:
            libs = resolve_result if isinstance(resolve_result, list) else resolve_result.get("results", [])
            if libs:
                lib_id = libs[0].get("id", "")
                if lib_id:
                    docs = _c7_request("context", {"libraryId": lib_id, "query": query, "tokens": "5000"})
                    if docs:
                        context_text = docs.get("context", "")
                        return {
                            "source": "context7",
                            "library": library,
                            "library_id": lib_id,
                            "query": query,
                            "context": context_text[:20000] if context_text else "Не найдено",
                            "sources_count": len(docs.get("sources", [])),
                        }

    return _ddgs_fallback(query, library)
