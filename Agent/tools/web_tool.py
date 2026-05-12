"""Инструменты web_search / web_fetch для агента Lorne.

Кэш, компактный вывод для экономии токенов, явный список ``sources`` для ссылок в UI.
"""
from __future__ import annotations

import hashlib
import html as html_mod
import re
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool


def _http_user_agent(short: bool = False) -> str:
    """Строка User-Agent для исходящих HTTP-запросов инструментов."""
    try:
        from Interface.branding import user_agent_fragment
        frag = user_agent_fragment()
    except ImportError:
        frag = "Lorne/0.98"
    if short:
        return f"Mozilla/5.0 (compatible; {frag})"
    return f"Mozilla/5.0 (compatible; {frag}; +https://github.com)"


_search_cache: Dict[str, tuple] = {}
_fetch_cache: Dict[str, tuple] = {}
_SEARCH_TTL = 300
_FETCH_TTL = 600


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


# ─── Helpers: economy + compact model view ─────────────────────────

def _truncate_snippet(text: str, max_chars: int) -> str:
    t = (text or "").replace("\n", " ").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _smart_truncate(text: str, max_length: int) -> Tuple[str, int]:
    """Обрезка по абзацам, затем по символам. Возвращает (обрезанный, исходная длина)."""
    raw_len = len(text)
    if raw_len <= max_length:
        return text, raw_len
    chunks = text.split("\n\n")
    acc = []
    cur = 0
    for ch in chunks:
        sep = 2 if acc else 0
        if cur + sep + len(ch) <= max_length:
            acc.append(ch)
            cur += sep + len(ch)
        else:
            room = max_length - cur - sep
            if room > 200:
                acc.append(ch[:room].rstrip() + "…")
            break
    out = "\n\n".join(acc) if acc else text[:max_length]
    if len(out) > max_length:
        out = text[: max_length - 80].rstrip() + "\n\n… [обрезано] …\n\n" + text[-60:]
    return out, raw_len


def _extract_code_blocks(raw_html: str) -> List[str]:
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
                blocks.append(text[:2000])
    return blocks[:6]


def _html_to_text(raw_html: str, extract_code: bool = True) -> Tuple[str, List[str]]:
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


def _build_model_compact_search(query: str, refined: str, rows: List[Dict[str, Any]]) -> str:
    lines = [f"[web_search] запрос: {query}"]
    if refined != query:
        lines.append(f"уточнение: {refined}")
    lines.append("результаты (заголовок → URL, короткий сниппет):")
    for i, r in enumerate(rows, 1):
        title = _truncate_snippet(r.get("title") or "", 72)
        url = (r.get("url") or "").strip()
        sn = _truncate_snippet(r.get("snippet") or "", 140)
        lines.append(f"{i}. {title}")
        lines.append(f"   {url}")
        if sn:
            lines.append(f"   «{sn}»")
    lines.append("")
    lines.append("Дальше: выбери 1–2 URL и при необходимости вызови web_fetch(url) только по нужным страницам.")
    return "\n".join(lines)


def _build_model_compact_fetch(url: str, text: str, raw_len: int, code_blocks: List[str]) -> str:
    lines = [
        f"[web_fetch] {url}",
        f"извлечено символов (до обрезки): {raw_len}",
        "— текст (сжато) —",
        text,
    ]
    if code_blocks:
        lines.append("")
        lines.append("— фрагменты кода (сокращены) —")
        for i, b in enumerate(code_blocks[:4], 1):
            lines.append(f"### block {i}")
            lines.append(b[:1200] + ("…" if len(b) > 1200 else ""))
    lines.append("")
    lines.append(f"источник: {url}")
    return "\n".join(lines)


def _build_model_compact_search_read(query: str, pages: List[Dict[str, Any]]) -> str:
    lines = [f"[web_search_and_read] запрос: {query}", f"просмотрено страниц: {len(pages)}", ""]
    for i, p in enumerate(pages, 1):
        title = _truncate_snippet(p.get("title") or "", 70)
        url = (p.get("url") or "").strip()
        sn = _truncate_snippet(p.get("snippet") or "", 100)
        body = (p.get("content") or "").strip()
        body_t, _ = _smart_truncate(body, 1800)
        lines.append(f"=== {i}. {title}")
        lines.append(url)
        if sn:
            lines.append(f"сниппет DDG: {sn}")
        lines.append("--- содержимое (сжато) ---")
        lines.append(body_t if body_t else "(не удалось загрузить HTML)")
        cbs = p.get("code_blocks") or []
        if cbs:
            lines.append("--- код ---")
            for j, c in enumerate(cbs[:2], 1):
                lines.append(f"[{j}] {str(c)[:900]}{'…' if len(str(c)) > 900 else ''}")
        lines.append("")
    lines.append("Опирайся на факты из текста выше; не выдумывай URL вне списка.")
    return "\n".join(lines)


def _normalize_sources(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for r in rows:
        u = (r.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append({"url": u, "title": (r.get("title") or "")[:240]})
    return out


# ─── Web search ────────────────────────────────────────────────────

@tool
def web_search(query: str, max_results: int = 4, snippet_chars: int = 140) -> Dict[str, Any]:
    """Поиск в интернете: короткие сниппеты и список URL. Для полного текста страницы вызови web_fetch(url).
    max_results — не больше 8; snippet_chars — длина сниппета (экономия токенов)."""
    max_results = max(1, min(int(max_results), 8))
    snippet_chars = max(40, min(int(snippet_chars), 320))
    try:
        from ddgs import DDGS
    except ImportError:
        return {"error": "ddgs не установлен", "hint": "pip install ddgs"}

    cache_key = hashlib.md5(f"{query}:{max_results}:{snippet_chars}".encode()).hexdigest()
    cached = _cache_get(_search_cache, cache_key, _SEARCH_TTL)
    if cached:
        cached["cached"] = True
        return cached

    docs_keywords = ["docs", "documentation", "api", "reference", "tutorial", "guide", "how to"]
    is_docs_search = any(kw in query.lower() for kw in docs_keywords)

    refined_query = query
    if is_docs_search and "site:" not in query.lower():
        refined_query += " (site:docs.python.org OR site:npmjs.com OR site:github.com OR site:developer.mozilla.org)"

    try:
        results = DDGS().text(refined_query, max_results=max_results)
        formatted = []
        for r in results:
            formatted.append({
                "title": (r.get("title") or "")[:200],
                "url": (r.get("href") or "")[:500],
                "snippet": _truncate_snippet(r.get("body") or "", snippet_chars),
            })

        sources = _normalize_sources(formatted)
        compact = _build_model_compact_search(query, refined_query, formatted)

        result: Dict[str, Any] = {
            "query": query,
            "refined_query": refined_query,
            "results": formatted,
            "sources": sources,
            "_model_compact": compact,
            "cached": False,
        }
        _cache_set(_search_cache, cache_key, result)
        return result
    except Exception as e:
        return {"query": query, "error": type(e).__name__, "detail": str(e)}


# ─── Web fetch ─────────────────────────────────────────────────────

@tool
def web_fetch(url: str, max_length: int = 4500, code_block_chars: int = 1200) -> Dict[str, Any]:
    """Загружает одну страницу: текст сжат до max_length (умная обрезка). code_block_chars — лимит на блок кода.
    Предпочитай web_search → несколько узких web_fetch вместо web_search_and_read на большие объёмы."""
    max_length = max(800, min(int(max_length), 24_000))
    code_block_chars = max(200, min(int(code_block_chars), 4000))
    cache_key = hashlib.md5(f"{url}:{max_length}:{code_block_chars}".encode()).hexdigest()
    cached = _cache_get(_fetch_cache, cache_key, _FETCH_TTL)
    if cached:
        cached["cached"] = True
        return cached

    headers = {
        "User-Agent": _http_user_agent(short=False),
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
    text_trim, _ = _smart_truncate(text, max_length)
    trimmed_blocks = []
    for b in code_blocks[:5]:
        trimmed_blocks.append(b[:code_block_chars] + ("…" if len(b) > code_block_chars else ""))

    sources = [{"url": url, "title": ""}]
    compact = _build_model_compact_fetch(url, text_trim, total_len, trimmed_blocks)

    result = {
        "url": url,
        "content": text_trim,
        "length": total_len,
        "code_blocks": trimmed_blocks,
        "sources": sources,
        "_model_compact": compact,
        "cached": False,
    }
    _cache_set(_fetch_cache, cache_key, result)
    return result


# ─── Combined search + read ────────────────────────────────────────

@tool
def web_search_and_read(
    query: str,
    max_pages: int = 2,
    chars_per_page: int = 2000,
    snippet_chars: int = 100,
) -> Dict[str, Any]:
    """Поиск + чтение первых страниц. По умолчанию мало страниц и короткий текст — экономия токенов.
    Для глубины лучше: web_search → web_fetch по выбранным URL."""
    max_pages = max(1, min(int(max_pages), 4))
    chars_per_page = max(600, min(int(chars_per_page), 8000))
    snippet_chars = max(40, min(int(snippet_chars), 240))
    try:
        from ddgs import DDGS
    except ImportError:
        return {"error": "ddgs не установлен", "hint": "pip install ddgs"}

    cache_key = hashlib.md5(
        f"{query}:{max_pages}:{chars_per_page}:{snippet_chars}".encode(),
    ).hexdigest()
    cached = _cache_get(_search_cache, f"sr:{cache_key}", _SEARCH_TTL)
    if cached:
        cached["cached"] = True
        return cached

    try:
        results = list(DDGS().text(query, max_results=max_pages + 2))
    except Exception as e:
        return {"query": query, "error": str(e)}

    pages: List[Dict[str, Any]] = []
    for r in results[:max_pages]:
        url = (r.get("href") or "").strip()
        if not url:
            continue

        page_data: Dict[str, Any] = {
            "title": (r.get("title") or "")[:200],
            "url": url,
            "snippet": _truncate_snippet(r.get("body") or "", snippet_chars),
            "content": "",
            "code_blocks": [],
        }

        try:
            headers = {
                "User-Agent": _http_user_agent(short=True),
                "Accept": "text/html,text/plain",
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                ct = resp.headers.get("Content-Type", "")
                if "text" in ct or "html" in ct:
                    raw = resp.read().decode("utf-8", errors="ignore")
                    text, code_blocks = _html_to_text(raw)
                    body, _ = _smart_truncate(text, chars_per_page)
                    page_data["content"] = body
                    page_data["code_blocks"] = [
                        c[:900] + ("…" if len(c) > 900 else "") for c in code_blocks[:3]
                    ]
        except Exception:
            pass

        pages.append(page_data)

    sources = _normalize_sources(pages)
    compact = _build_model_compact_search_read(query, pages)

    out: Dict[str, Any] = {
        "query": query,
        "pages_fetched": len(pages),
        "pages": pages,
        "sources": sources,
        "_model_compact": compact,
        "cached": False,
    }
    _cache_set(_search_cache, f"sr:{cache_key}", out)
    return out
