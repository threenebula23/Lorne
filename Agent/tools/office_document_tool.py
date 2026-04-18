"""Чтение и запись Office/PDF: DOCX со стилями Word, простой PDF с типографикой ReportLab, .doc через antiword (если есть).

Стили DOCX — как в Word: Normal, Title, Heading 1…9, Quote, Intense Quote, Subtitle и др. из шаблона документа.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from langchain_core.tools import tool

try:
    from ..path_utils import resolve_abs_path
except ImportError:
    from Agent.path_utils import resolve_abs_path

_STYLE_DOC = (
    "Стили абзацев как в Word: Normal, Title, Heading 1 … Heading 9, Subtitle, "
    "Quote, Intense Quote, Caption, List Paragraph. Для PDF-секций role: title, h1, h2, body."
)


def _compact_read(path: str, paragraphs: List[Dict[str, Any]], total: int, extra: str = "") -> str:
    lines = [f"[office_document_read] {path}", f"абзацев в выборке: {len(paragraphs)} из {total}", extra, "---"]
    for p in paragraphs[:40]:
        lines.append(f"[{p.get('i')}] ({p.get('style')}) {str(p.get('text', ''))[:500]}")
    if len(paragraphs) > 40:
        lines.append(f"… ещё {len(paragraphs) - 40} абзацев …")
    return "\n".join(lines)


def _read_doc_antiword(path: Path) -> Tuple[str, str]:
    try:
        r = subprocess.run(
            ["antiword", "-m", "UTF-8.txt", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode == 0:
            return r.stdout or "", ""
        return "", (r.stderr or f"antiword exit {r.returncode}")[:400]
    except FileNotFoundError:
        return "", "antiword не найден (установите пакет antiword для чтения .doc)"
    except Exception as e:
        return "", str(e)[:400]


def _read_docx_paragraphs(path: Path, max_paragraphs: int) -> Tuple[List[Dict[str, Any]], int, str]:
    try:
        from docx import Document
    except ImportError:
        return [], 0, "python-docx не установлен: pip install python-docx"

    doc = Document(str(path))
    total = len(doc.paragraphs)
    out: List[Dict[str, Any]] = []
    for i, p in enumerate(doc.paragraphs[: max(1, max_paragraphs)]):
        try:
            st = p.style.name if p.style is not None else "Default"
        except Exception:
            st = "Default"
        out.append({"i": i, "style": st, "text": p.text or ""})
    return out, total, ""


def _read_pdf_pages(path: Path, max_pages: int, max_chars: int) -> Tuple[List[Dict[str, Any]], int, str]:
    try:
        import fitz
    except ImportError:
        return [], 0, "pymupdf не установлен: pip install pymupdf"

    doc = fitz.open(str(path))
    n = min(len(doc), max(1, max_pages))
    out: List[Dict[str, Any]] = []
    used = 0
    for pi in range(n):
        text = doc.load_page(pi).get_text("text") or ""
        chunk = text[: max_chars - used] if max_chars > used else ""
        used += len(chunk)
        out.append({"i": pi, "style": f"Page {pi + 1}", "text": chunk})
        if used >= max_chars:
            break
    doc.close()
    return out, len(doc), ""


@tool
def office_document_read(
    file_path: str,
    max_paragraphs: int = 200,
    max_chars: int = 120_000,
) -> Dict[str, Any]:
    """Читает .docx (абзацы + имена стилей Word), .pdf (текст по страницам) или .doc (только текст, нужен antiword).
    Для правок стилей и текста используй docx_document_patch_paragraphs / docx_document_append_paragraphs."""
    path = resolve_abs_path(file_path)
    if not path.is_file():
        return {"error": "not_found", "path": str(path)}

    suf = path.suffix.lower()
    max_paragraphs = max(1, min(int(max_paragraphs), 2000))
    max_chars = max(2000, min(int(max_chars), 500_000))

    paragraphs: List[Dict[str, Any]] = []
    total = 0
    hint = ""

    if suf == ".docx":
        paragraphs, total, err = _read_docx_paragraphs(path, max_paragraphs)
        if err:
            return {"error": "import", "detail": err, "path": str(path)}
        # trim by max_chars
        acc = 0
        trimmed: List[Dict[str, Any]] = []
        for p in paragraphs:
            t = p.get("text") or ""
            if acc + len(t) > max_chars:
                room = max_chars - acc
                if room > 50:
                    trimmed.append({**p, "text": t[:room] + "…"})
                break
            trimmed.append(p)
            acc += len(t)
        paragraphs = trimmed
    elif suf == ".pdf":
        pages = max(1, min(max_paragraphs, 500))
        paragraphs, total, err = _read_pdf_pages(path, pages, max_chars)
        if err:
            return {"error": "import", "detail": err, "path": str(path)}
    elif suf == ".doc":
        raw, err = _read_doc_antiword(path)
        if err and not raw.strip():
            return {
                "path": str(path),
                "error": "doc_read_failed",
                "detail": err,
                "hint": "Конвертируйте .doc → .docx (LibreOffice) или установите antiword.",
            }
        # одна псевдо-страница
        paragraphs = [{"i": 0, "style": "Plain", "text": raw[:max_chars]}]
        total = 1
        hint = "Только текст без стилей (.doc). Для стилей сохраните как .docx."
    else:
        return {
            "error": "unsupported",
            "path": str(path),
            "hint": "Поддерживаются .docx, .pdf, .doc (через antiword).",
        }

    full_text = "\n\n".join((p.get("text") or "") for p in paragraphs)
    compact = _compact_read(str(path), paragraphs, total, hint)
    return {
        "path": str(path),
        "format": suf.lstrip("."),
        "paragraphs": paragraphs,
        "paragraph_count_sampled": len(paragraphs),
        "paragraph_count_total": total,
        "full_text": full_text[: min(len(full_text), max_chars)],
        "hint": hint or _STYLE_DOC,
        "_model_compact": compact,
    }


def _resolve_paragraph_style(doc: Any, name: str) -> Any:
    try:
        return doc.styles[name]
    except Exception:
        try:
            return doc.styles["Normal"]
        except Exception:
            return doc.paragraphs[0].style if doc.paragraphs else None


def _add_block(doc: Any, text: str, style: str) -> None:
    style = (style or "Normal").strip()
    if style.lower() in ("title",):
        doc.add_heading(text, level=0)
        return
    m = re.match(r"heading\s*(\d+)", style, re.I)
    if m:
        lvl = min(9, max(1, int(m.group(1))))
        doc.add_heading(text, level=lvl)
        return
    try:
        doc.add_paragraph(text, style=style)
    except Exception:
        doc.add_paragraph(text, style="Normal")


def _parse_json_list(raw: str, label: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"Невалидный JSON ({label}): {e}"
    if not isinstance(data, list):
        return None, f"{label}: ожидается JSON-массив объектов"
    return data, None


@tool
def docx_document_create(file_path: str, paragraphs_json: str) -> Dict[str, Any]:
    """Создаёт новый .docx. paragraphs_json: [{"text":"...","style":"Title|Heading 1|Normal|..."}, ...]."""
    try:
        from docx import Document
    except ImportError:
        return {"error": "import", "detail": "pip install python-docx"}

    items, err = _parse_json_list(paragraphs_json, "paragraphs_json")
    if err:
        return {"error": "bad_json", "detail": err}

    path = resolve_abs_path(file_path)
    if path.suffix.lower() != ".docx":
        path = path.with_suffix(".docx")
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    for it in items:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text", ""))
        style = str(it.get("style", "Normal"))
        if text or style != "Normal":
            _add_block(doc, text, style)

    doc.save(str(path))
    return {"path": str(path), "action": "created", "paragraphs_written": len(items)}


@tool
def docx_document_append_paragraphs(file_path: str, paragraphs_json: str) -> Dict[str, Any]:
    """Добавляет в конец существующего .docx абзацы. paragraphs_json как в docx_document_create."""
    try:
        from docx import Document
    except ImportError:
        return {"error": "import", "detail": "pip install python-docx"}

    path = resolve_abs_path(file_path)
    if not path.is_file():
        return {"error": "not_found", "path": str(path)}
    if path.suffix.lower() != ".docx":
        return {"error": "not_docx", "path": str(path)}

    items, err = _parse_json_list(paragraphs_json, "paragraphs_json")
    if err:
        return {"error": "bad_json", "detail": err}

    doc = Document(str(path))
    n0 = len(doc.paragraphs)
    for it in items:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text", ""))
        style = str(it.get("style", "Normal"))
        _add_block(doc, text, style)
    doc.save(str(path))
    return {
        "path": str(path),
        "action": "appended",
        "paragraphs_before": n0,
        "paragraphs_after": len(doc.paragraphs),
    }


@tool
def docx_document_patch_paragraphs(file_path: str, patches_json: str) -> Dict[str, Any]:
    """Правка абзацев по индексу (0-based). patches_json:
    [{"paragraph_index": 0, "text": "новый текст", "style": "Heading 2"}, ...]
    Поле style можно опустить — останется прежний стиль (кроме смены через text)."""
    try:
        from docx import Document
    except ImportError:
        return {"error": "import", "detail": "pip install python-docx"}

    path = resolve_abs_path(file_path)
    if not path.is_file():
        return {"error": "not_found", "path": str(path)}
    if path.suffix.lower() != ".docx":
        return {"error": "not_docx", "path": str(path)}

    patches, err = _parse_json_list(patches_json, "patches_json")
    if err:
        return {"error": "bad_json", "detail": err}

    doc = Document(str(path))
    total = len(doc.paragraphs)
    applied = 0
    for p in patches:
        if not isinstance(p, dict):
            continue
        try:
            idx = int(p.get("paragraph_index", p.get("i", -1)))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= total:
            return {
                "error": "index_out_of_range",
                "paragraph_index": idx,
                "total_paragraphs": total,
            }
        para = doc.paragraphs[idx]
        if "text" in p:
            para.text = str(p.get("text", ""))
        st = p.get("style")
        if st:
            try:
                para.style = _resolve_paragraph_style(doc, str(st))
            except Exception:
                pass
        applied += 1

    doc.save(str(path))
    return {"path": str(path), "action": "patched", "patches_applied": applied, "paragraphs_total": total}


@tool
def pdf_styled_document_create(file_path: str, sections_json: str, title: str = "") -> Dict[str, Any]:
    """Создаёт PDF с «логическими» стилями (заголовки и body через ReportLab). Перезаписывает файл.
    sections_json: [{"role":"title|h1|h2|body","text":"..."}, ...]
    role задаёт размер/начертание как у заголовков в Word (упрощённо)."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        return {"error": "import", "detail": "pip install reportlab"}

    items, err = _parse_json_list(sections_json, "sections_json")
    if err:
        return {"error": "bad_json", "detail": err}

    path = resolve_abs_path(file_path)
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    story: list = []
    if title.strip():
        story.append(Paragraph(escape(title.strip()), styles["Title"]))
        story.append(Spacer(1, 0.3 * cm))

    for it in items:
        if not isinstance(it, dict):
            continue
        role = str(it.get("role", "body")).lower().strip()
        raw = str(it.get("text", ""))
        safe = escape(raw).replace("\n", "<br/>")
        if role in ("title",):
            story.append(Paragraph(safe, styles["Title"]))
        elif role in ("h1", "heading1", "heading 1"):
            story.append(Paragraph(safe, styles["Heading1"]))
        elif role in ("h2", "heading2", "heading 2"):
            story.append(Paragraph(safe, styles["Heading2"]))
        elif role in ("h3", "heading3"):
            story.append(Paragraph(safe, styles["Heading3"]))
        elif role in ("quote", "quotation"):
            story.append(Paragraph(safe, styles["Quote"]))
        else:
            story.append(Paragraph(safe, styles["Normal"]))
        story.append(Spacer(1, 0.15 * cm))

    doc = SimpleDocTemplate(str(path), pagesize=A4)
    doc.build(story)
    return {"path": str(path), "action": "pdf_created", "sections": len(items)}
