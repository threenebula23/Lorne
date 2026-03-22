"""Web search and page fetch tools for TCA agent.

Features:
- In-memory caching with TTL
- Code block extraction from HTML
- Combined search+read tool for convenience
"""
from __future__ import annotations

import hashlib
import html as html_mod
import re
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

# ─── Cache ──────────────────────────────────────────────────────────

_search_cache: Dict[str, tuple] = {}  # hash -> (timestamp, result)
_fetch_cache: Dict[str, tuple] = {}
_SEARCH_TTL = 300  # 5 min
_FETCH_TTL = 600   # 10 min


def _cache_get(cache: dict, key: str, ttl: int) -> Optional[Any]:
    if key in cache:
        ts, data = cache[key]
        if time.time() - ts < ttl:
            return data
        del cache[key]
    return None


def _cache_set(cache: dict, key: str, data: Any) -> None:
    cache[key] = (time.time(), data)
    if len(cache) > 200:
        oldest = min(cache, key=lambda k: cache[k][0])
        del cache[oldest]


# ─── HTML parsing ──────────────────────────────────────────────────

def _extract_code_blocks(raw_html: str) -> List[str]:
    """Extract <code> and <pre> blocks preserving their content."""
    blocks: List[str] = []
    for pattern in [
        r"<pre[^>]*><code[^>]*>(.*?)</code></pre>",
        r"<pre[^>]*>(.*?)</pre>",
        r"<code[^>]*>(.*?)</code>",
    ]:
        for match in re.finditer(pattern, raw_html, re.DOTALL | re.IGNORECASE):
            text = html_mod.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
            text = text.strip()
            if len(text) > 10:
                blocks.append(text)
    return blocks[:10]


def _html_to_text(raw_html: str, extract_code: bool = True) -> tuple:
    """Strip HTML → plain text. Returns (text, code_blocks)."""
    code_blocks = _extract_code_blocks(raw_html) if extract_code else []

    text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)

    text = re.sub(r"<(br|hr|/p|/div|/li|/tr|/h\d)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), code_blocks


# ─── Web search ────────────────────────────────────────────────────

@tool
def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Поиск в интернете. Возвращает заголовки, URL и сниппеты.
    Используй для поиска документации, актуальной информации, примеров кода."""
    try:
        from ddgs import DDGS
    except ImportError:
        return {"error": "ddgs не установлен", "hint": "pip install ddgs"}

    cache_key = hashlib.md5(f"{query}:{max_results}".encode()).hexdigest()
    cached = _cache_get(_search_cache, cache_key, _SEARCH_TTL)
    if cached:
        cached["cached"] = True
        return cached

    docs_keywords = ["docs", "documentation", "api", "reference", "tutorial", "guide", "how to"]
    is_docs_search = any(kw in query.lower() for kw in docs_keywords)

    refined_query = query
    if is_docs_search and "site:" not in query:
        refined_query += " (site:docs.python.org OR site:npmjs.com OR site:github.com OR site:developer.mozilla.org)"

    try:
        results = DDGS().text(refined_query, max_results=max_results)
        formatted = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in results
        ]

        result = {
            "query": query,
            "refined_query": refined_query,
            "results": formatted,
            "cached": False,
        }
        _cache_set(_search_cache, cache_key, result)
        return result
    except Exception as e:
        return {"query": query, "error": type(e).__name__, "detail": str(e)}


# ─── Web fetch ─────────────────────────────────────────────────────

@tool
def web_fetch(url: str, max_length: int = 8000) -> Dict[str, Any]:
    """Загружает веб-страницу и возвращает текстовое содержимое.
    Автоматически извлекает блоки кода из HTML."""
    cache_key = hashlib.md5(url.encode()).hexdigest()
    cached = _cache_get(_fetch_cache, cache_key, _FETCH_TTL)
    if cached:
        cached["cached"] = True
        return cached

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TCA/2.0; +https://github.com)",
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

    text, code_blocks = _html_to_text(raw)
    total_len = len(text)

    if total_len > max_length:
        text = text[:max_length] + f"\n\n… [обрезано, всего {total_len} символов]"

    result = {
        "url": url,
        "content": text,
        "length": total_len,
        "code_blocks": code_blocks[:5],
        "cached": False,
    }
    _cache_set(_fetch_cache, cache_key, result)
    return result


# ─── Combined search + read ────────────────────────────────────────

@tool
def web_search_and_read(query: str, max_pages: int = 3) -> Dict[str, Any]:
    """Поиск в интернете + чтение топ-страниц. Комбинированный инструмент:
    ищет через DuckDuckGo, затем загружает содержимое лучших результатов.
    Удобнее чем web_search → web_fetch по отдельности."""
    try:
        from ddgs import DDGS
    except ImportError:
        return {"error": "ddgs не установлен", "hint": "pip install ddgs"}

    try:
        results = DDGS().text(query, max_results=max_pages + 2)
    except Exception as e:
        return {"query": query, "error": str(e)}

    pages: List[Dict[str, Any]] = []
    for r in results[:max_pages]:
        url = r.get("href", "")
        if not url:
            continue

        page_data = {
            "title": r.get("title", ""),
            "url": url,
            "snippet": r.get("body", ""),
            "content": "",
            "code_blocks": [],
        }

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; TCA/2.0)",
                "Accept": "text/html,text/plain",
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                ct = resp.headers.get("Content-Type", "")
                if "text" in ct or "html" in ct:
                    raw = resp.read().decode("utf-8", errors="ignore")
                    text, code_blocks = _html_to_text(raw)
                    page_data["content"] = text[:4000]
                    page_data["code_blocks"] = code_blocks[:3]
        except Exception:
            pass

        pages.append(page_data)

    return {
        "query": query,
        "pages_fetched": len(pages),
        "pages": pages,
    }
