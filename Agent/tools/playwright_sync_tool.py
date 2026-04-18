"""Интерактивная автоматизация сайтов через Playwright Python API (sync).

Документация: https://github.com/microsoft/playwright-python
После `pip install playwright` выполните: `playwright install chromium`
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from langchain_core.tools import tool

try:
    from ..path_utils import resolve_abs_path
except ImportError:
    from Agent.path_utils import resolve_abs_path


def _pw_err(e: Exception) -> str:
    s = str(e).lower()
    if "executable doesn't exist" in s or "browserType.launch" in s:
        return (
            "Браузер Playwright не установлен. Выполните в venv: playwright install chromium"
        )
    return str(e)[:2000]


def _with_page(url: str, fn, timeout_ms: int = 45_000):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"error": "import", "detail": "pip install playwright && playwright install chromium"}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                out = fn(page)
                return out if isinstance(out, dict) else {"result": out}
            finally:
                browser.close()
    except Exception as e:
        return {"error": _pw_err(e)}


@tool
def playwright_sync_page_text(
    url: str,
    selector: str = "body",
    wait_ms: int = 1500,
) -> Dict[str, Any]:
    """Открыть URL и вернуть text_content выбранного элемента (Chromium headless)."""
    def _run(page):
        if wait_ms > 0:
            page.wait_for_timeout(int(wait_ms))
        el = page.query_selector(selector)
        text = (el.inner_text() if el else "") or ""
        return {"url": url, "selector": selector, "text": text[:50_000]}

    return _with_page(url, _run)


@tool
def playwright_sync_click(
    url: str,
    selector: str,
    wait_after_ms: int = 2000,
) -> Dict[str, Any]:
    """Перейти на URL, кликнуть по selector, подождать, вернуть URL страницы и заголовок."""
    def _run(page):
        page.click(selector, timeout=15_000)
        if wait_after_ms > 0:
            page.wait_for_timeout(int(wait_after_ms))
        return {
            "url_after": page.url,
            "title": page.title() or "",
        }

    return _with_page(url, _run)


@tool
def playwright_sync_fill_and_optional_click(
    url: str,
    field_selector: str,
    text: str,
    button_selector: str = "",
) -> Dict[str, Any]:
    """Заполнить поле ввода и опционально нажать кнопку (отправка формы)."""
    def _run(page):
        page.fill(field_selector, text, timeout=15_000)
        if (button_selector or "").strip():
            page.click(button_selector.strip(), timeout=15_000)
            page.wait_for_timeout(1500)
        return {"url_after": page.url, "title": page.title() or ""}

    return _with_page(url, _run)


@tool
def playwright_sync_screenshot(
    url: str,
    output_path: str,
    full_page: bool = False,
) -> Dict[str, Any]:
    """Скриншот страницы (viewport или full_page)."""
    out = Path(resolve_abs_path(output_path))
    out.parent.mkdir(parents=True, exist_ok=True)

    def _run(page):
        page.wait_for_timeout(1200)
        page.screenshot(path=str(out), full_page=bool(full_page))
        return {"saved": str(out.resolve())}

    r = _with_page(url, _run)
    if "error" in r:
        return r
    return {"ok": True, **r}
