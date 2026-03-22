"""Browser automation tool using Playwright CLI for agent mode.

Provides web scraping, page interaction, and screenshot capabilities
via Playwright's CLI interface (no server needed).
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool


def _run_playwright_script(script: str, timeout: int = 30) -> dict:
    """Execute a Playwright script via Node.js subprocess."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".mjs", delete=False) as f:
        f.write(script)
        f.flush()
        script_path = f.name

    try:
        result = subprocess.run(
            ["node", script_path],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(Path.cwd()),
        )
        return {
            "stdout": result.stdout[:5000],
            "stderr": result.stderr[:2000],
            "exit_code": result.returncode,
        }
    except FileNotFoundError:
        return {"error": "Node.js not found. Install Node.js to use browser tools."}
    except subprocess.TimeoutExpired:
        return {"error": f"Browser script timed out ({timeout}s)"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        try:
            Path(script_path).unlink()
        except Exception:
            pass


@tool
def browser_get_text(url: str, selector: str = "body", wait_ms: int = 3000) -> str:
    """Fetch text content from a web page using a headless browser.

    Args:
        url: The URL to navigate to.
        selector: CSS selector to extract text from (default: 'body').
        wait_ms: Milliseconds to wait for the page to load.
    """
    script = f"""
import {{ chromium }} from 'playwright';

(async () => {{
    const browser = await chromium.launch({{ headless: true }});
    const page = await browser.newPage();
    try {{
        await page.goto({json.dumps(url)}, {{ waitUntil: 'domcontentloaded', timeout: 15000 }});
        await page.waitForTimeout({wait_ms});
        const el = await page.$('{selector}');
        const text = el ? await el.textContent() : 'Element not found';
        console.log(JSON.stringify({{ text: text.substring(0, 5000) }}));
    }} catch (e) {{
        console.log(JSON.stringify({{ error: e.message }}));
    }} finally {{
        await browser.close();
    }}
}})();
"""
    result = _run_playwright_script(script)
    if "error" in result:
        return f"Browser error: {result['error']}"
    try:
        data = json.loads(result["stdout"])
        return data.get("text", data.get("error", "No output"))
    except Exception:
        return result.get("stdout", "") or result.get("stderr", "Unknown error")


@tool
def browser_screenshot(url: str, output_path: str = "screenshot.png",
                       full_page: bool = False) -> str:
    """Take a screenshot of a web page.

    Args:
        url: The URL to screenshot.
        output_path: Where to save the screenshot.
        full_page: Whether to capture the full page or just the viewport.
    """
    abs_path = str(Path(output_path).resolve())
    script = f"""
import {{ chromium }} from 'playwright';

(async () => {{
    const browser = await chromium.launch({{ headless: true }});
    const page = await browser.newPage();
    try {{
        await page.goto({json.dumps(url)}, {{ waitUntil: 'domcontentloaded', timeout: 15000 }});
        await page.waitForTimeout(2000);
        await page.screenshot({{ path: {json.dumps(abs_path)}, fullPage: {'true' if full_page else 'false'} }});
        console.log(JSON.stringify({{ saved: {json.dumps(abs_path)} }}));
    }} catch (e) {{
        console.log(JSON.stringify({{ error: e.message }}));
    }} finally {{
        await browser.close();
    }}
}})();
"""
    result = _run_playwright_script(script)
    if "error" in result:
        return f"Screenshot error: {result['error']}"
    try:
        data = json.loads(result["stdout"])
        return f"Screenshot saved: {data.get('saved', abs_path)}"
    except Exception:
        return result.get("stdout", "") or result.get("stderr", "Unknown error")


@tool
def browser_click_and_get(url: str, click_selector: str,
                          result_selector: str = "body",
                          wait_ms: int = 3000) -> str:
    """Navigate to a page, click an element, then extract text.

    Args:
        url: The URL to navigate to.
        click_selector: CSS selector of the element to click.
        result_selector: CSS selector to extract text from after clicking.
        wait_ms: Milliseconds to wait after clicking.
    """
    script = f"""
import {{ chromium }} from 'playwright';

(async () => {{
    const browser = await chromium.launch({{ headless: true }});
    const page = await browser.newPage();
    try {{
        await page.goto({json.dumps(url)}, {{ waitUntil: 'domcontentloaded', timeout: 15000 }});
        await page.waitForTimeout(1000);
        await page.click('{click_selector}');
        await page.waitForTimeout({wait_ms});
        const el = await page.$('{result_selector}');
        const text = el ? await el.textContent() : 'Element not found after click';
        console.log(JSON.stringify({{ text: text.substring(0, 5000) }}));
    }} catch (e) {{
        console.log(JSON.stringify({{ error: e.message }}));
    }} finally {{
        await browser.close();
    }}
}})();
"""
    result = _run_playwright_script(script)
    if "error" in result:
        return f"Browser error: {result['error']}"
    try:
        data = json.loads(result["stdout"])
        return data.get("text", data.get("error", "No output"))
    except Exception:
        return result.get("stdout", "") or result.get("stderr", "Unknown error")


@tool
def browser_evaluate(url: str, js_expression: str) -> str:
    """Navigate to a page and evaluate a JavaScript expression.

    Args:
        url: The URL to navigate to.
        js_expression: JavaScript expression to evaluate in the page context.
    """
    escaped = json.dumps(js_expression)
    script = f"""
import {{ chromium }} from 'playwright';

(async () => {{
    const browser = await chromium.launch({{ headless: true }});
    const page = await browser.newPage();
    try {{
        await page.goto({json.dumps(url)}, {{ waitUntil: 'domcontentloaded', timeout: 15000 }});
        await page.waitForTimeout(2000);
        const result = await page.evaluate({escaped});
        console.log(JSON.stringify({{ result: String(result).substring(0, 5000) }}));
    }} catch (e) {{
        console.log(JSON.stringify({{ error: e.message }}));
    }} finally {{
        await browser.close();
    }}
}})();
"""
    result = _run_playwright_script(script)
    if "error" in result:
        return f"Browser error: {result['error']}"
    try:
        data = json.loads(result["stdout"])
        return data.get("result", data.get("error", "No output"))
    except Exception:
        return result.get("stdout", "") or result.get("stderr", "Unknown error")
