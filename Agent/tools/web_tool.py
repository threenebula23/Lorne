"""Web search and page fetch tools for TCA agent.

Uses the `ddgs` package (metasearch via DuckDuckGo/Bing/Google/etc.)
for search and stdlib urllib for page fetching — no API keys needed.
"""
from __future__ import annotations

import html as html_mod
import re
import urllib.request
import urllib.error
from typing import Any, Dict, List

from langchain_core.tools import tool


@tool
def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Поиск в интернете. Возвращает заголовки, URL и сниппеты.
    Используй для поиска документации, актуальной информации, примеров кода и т.д."""
    try:
        from ddgs import DDGS
    except ImportError:
        return {
            "error": "ddgs не установлен",
            "hint": "pip install ddgs",
        }

    # Если запрос похож на поиск документации, добавляем ключевые слова
    docs_keywords = ["docs", "documentation", "api", "reference", "tutorial", "guide"]
    is_docs_search = any(kw in query.lower() for kw in docs_keywords)
    
    refined_query = query
    if is_docs_search and "site:" not in query:
        refined_query += " (site:docs.python.org OR site:npmjs.com OR site:github.com)"

    try:
        results = DDGS().text(refined_query, max_results=max_results)
        return {
            "query": query,
            "refined_query": refined_query,
            "results": [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ],
        }
    except Exception as e:
        return {"query": query, "error": type(e).__name__, "detail": str(e)}


def _html_to_text(raw_html: str) -> str:
    """Strip HTML tags, scripts, styles and return plain text."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(br|hr|/p|/div|/li|/tr|/h\d)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@tool
def web_fetch(url: str, max_length: int = 8000) -> Dict[str, Any]:
    """Загружает веб-страницу и возвращает текстовое содержимое (HTML → текст).
    Полезно для чтения документации, статей, Stack Overflow и т.д."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TCA/1.0; +https://github.com)",
        "Accept": "text/html,application/xhtml+xml,text/plain",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text" not in content_type and "html" not in content_type:
                return {"url": url, "error": "not_text", "content_type": content_type}
            raw = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return {"url": url, "error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"url": url, "error": "URLError", "detail": str(e.reason)}
    except Exception as e:
        return {"url": url, "error": type(e).__name__, "detail": str(e)}

    text = _html_to_text(raw)
    total_len = len(text)

    if total_len > max_length:
        text = text[:max_length] + f"\n\n… [обрезано, всего {total_len} символов]"

    return {"url": url, "content": text, "length": total_len}
