"""Трёхуровневое извлечение текста: файлы (мягко), изображения/скриншоты (средне), фото (жёсткий OCR).

Требует системный Tesseract и пакет pytesseract. PDF-текстовый слой — через pymupdf (опционально).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from langchain_core.tools import tool

try:
    from ..path_utils import resolve_abs_path
except ImportError:
    from Agent.path_utils import resolve_abs_path

_TEXT_EXT = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".html", ".htm",
    ".rst", ".log", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".adoc",
    ".tex", ".svg", ".py", ".js", ".ts", ".rs", ".go", ".java", ".c", ".h", ".cpp",
    ".sh", ".sql",
}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
_PDF_EXT = {".pdf"}

_MAX_SOFT_BYTES = 512_000


def _tesseract_langs() -> str:
    try:
        import pytesseract  # type: ignore
        langs = set(pytesseract.get_languages())
        parts = ["eng"]
        if "rus" in langs:
            parts.append("rus")
        return "+".join(parts)
    except Exception:
        return "eng"


def _check_tesseract() -> Tuple[bool, str]:
    try:
        import pytesseract  # type: ignore
        pytesseract.get_tesseract_version()
        return True, ""
    except Exception as e:
        return False, (
            f"Tesseract недоступен ({e}). Установите бинарник (например "
            "`tesseract` в PATH) и пакет `pip install pytesseract`."
        )


def _pil_open(path: Path) -> Any:
    from PIL import Image
    return Image.open(path)


def _resize_max_side(img: Any, max_side: int) -> Any:
    from PIL import Image
    w, h = img.size
    m = max(w, h)
    if m <= max_side:
        return img
    scale = max_side / m
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def _run_ocr(img: Any, psm: int) -> str:
    import pytesseract  # type: ignore
    from PIL import Image
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    lang = _tesseract_langs()
    cfg = f"--oem 3 --psm {psm}"
    return pytesseract.image_to_string(img, lang=lang, config=cfg) or ""


def _ocr_confidence_score(img: Any) -> float:
    """Средняя уверенность по словам (0–100), если доступно; иначе -1."""
    try:
        import pytesseract  # type: ignore
        from pytesseract import Output
        data = pytesseract.image_to_data(img, output_type=Output.DICT)
        confs = [int(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit() and int(c) >= 0]
        if not confs:
            return -1.0
        return sum(confs) / len(confs)
    except Exception:
        return -1.0


def _quality_flags(text: str, mean_conf: float, min_chars: int = 12) -> Tuple[str, bool]:
    t = (text or "").strip()
    if len(t) < min_chars:
        return "empty", True
    if mean_conf >= 0 and mean_conf < 55:
        return "low", True
    if len(t) < 40 and mean_conf >= 0 and mean_conf < 70:
        return "low", True
    return "good", False


def _truncate(text: str, max_chars: int) -> Tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    half = max_chars // 2
    return (
        text[:half]
        + "\n\n… [обрезано по max_chars] …\n\n"
        + text[-half:],
        True,
    )


def _compact_block(level: str, path: str, text: str, quality: str, use_vision: bool, extra: str = "") -> str:
    lines = [
        f"[{level}] {path}",
        f"качество_извлечения: {quality}",
        f"символов: {len(text.strip())}",
        "используй_vision_модели: да — если инструмент дал пустой/сомнительный текст, опирайся на изображение во вложении пользователя."
        if use_vision
        else "используй_vision_модели: опционально — при несоответствии ожиданиям проверь вложение глазами модели.",
    ]
    if extra:
        lines.append(extra)
    lines.append("--- текст ---")
    lines.append(text.strip() or "(пусто)")
    return "\n".join(lines)


def _read_pdf_text_layer(path: Path, max_pages: int) -> Tuple[str, str]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return "", "pymupdf не установлен (pip install pymupdf) — для сканов используй ocr_read_image_medium / ocr_read_photo_strong."

    parts: List[str] = []
    try:
        doc = fitz.open(path)
    except Exception as e:
        return "", f"не удалось открыть PDF: {e}"
    n = min(len(doc), max(1, max_pages))
    for i in range(n):
        try:
            parts.append(doc.load_page(i).get_text("text") or "")
        except Exception:
            parts.append("")
    doc.close()
    return "\n\n".join(parts).strip(), ""


@tool
def ocr_read_file_soft(
    file_path: str,
    max_chars: int = 80_000,
    max_pdf_pages: int = 40,
) -> Dict[str, Any]:
    """Уровень 1 (мягкий): текстовые файлы и PDF с текстовым слоем (без тяжёлого OCR по растру).
    Не подходит для .png/.jpg — для них `ocr_read_image_medium` или `ocr_read_photo_strong`."""
    path = resolve_abs_path(file_path)
    if not path.is_file():
        return {"error": "not_found", "path": str(path)}

    suf = path.suffix.lower()
    if suf in _IMAGE_EXT:
        return {
            "error": "wrong_tool",
            "path": str(path),
            "hint": "Растровое изображение: вызови `ocr_read_image_medium` (скрин/диаграмма) или "
            "`ocr_read_photo_strong` (фото с камеры). Затем при плохом тексте — опирайся на vision по вложению.",
        }

    max_chars = max(2000, min(int(max_chars), 400_000))
    max_pdf_pages = max(1, min(int(max_pdf_pages), 120))

    text = ""
    source = ""

    if suf in _TEXT_EXT or suf == "":
        try:
            raw = path.read_bytes()
            if len(raw) > _MAX_SOFT_BYTES:
                return {
                    "error": "file_too_large",
                    "path": str(path),
                    "hint": f"Файл > {_MAX_SOFT_BYTES} байт — используй read_file с offset/limit.",
                }
            text = raw.decode("utf-8", errors="replace")
            source = "plain_utf8"
        except OSError as e:
            return {"error": "read_failed", "detail": str(e), "path": str(path)}

    elif suf in _PDF_EXT:
        text, hint = _read_pdf_text_layer(path, max_pdf_pages)
        source = "pdf_text_layer"
        if not text.strip() and hint:
            return {
                "path": str(path),
                "text": "",
                "source": source,
                "quality": "empty",
                "use_vision_fallback": True,
                "hint": hint
                + " Если это скан — средний/высокий OCR по страницам как изображения или vision.",
                "_model_compact": _compact_block(
                    "ocr_read_file_soft",
                    str(path),
                    "",
                    "empty",
                    True,
                    hint,
                ),
            }
    else:
        return {
            "error": "unsupported_extension",
            "path": str(path),
            "hint": "Расширение не поддержано на мягком уровне. Попробуй read_file или OCR-инструмент для картинки.",
        }

    text, truncated = _truncate(text, max_chars)
    quality, use_vision = _quality_flags(text, -1.0, min_chars=8)
    if truncated:
        quality = "low" if quality == "good" else quality

    compact = _compact_block("ocr_read_file_soft", str(path), text, quality, use_vision, f"источник: {source}")
    return {
        "path": str(path),
        "text": text,
        "source": source,
        "quality": quality,
        "use_vision_fallback": use_vision,
        "truncated": truncated,
        "_model_compact": compact,
    }


@tool
def ocr_read_image_medium(image_path: str, max_side: int = 2400, max_chars: int = 60_000) -> Dict[str, Any]:
    """Уровень 2 (средний): скриншоты, UI, чёткие диаграммы, отсканированные документы с хорошим контрастом.
    Сначала вызывай этот инструмент для изображений; при слабом тексте — `ocr_read_photo_strong` или vision."""
    ok, err = _check_tesseract()
    if not ok:
        return {"error": "tesseract_missing", "detail": err, "use_vision_fallback": True}

    path = resolve_abs_path(image_path)
    if not path.is_file():
        return {"error": "not_found", "path": str(path)}

    suf = path.suffix.lower()
    if suf not in _IMAGE_EXT:
        return {
            "error": "not_an_image",
            "path": str(path),
            "hint": "Для не-картинок используй ocr_read_file_soft или read_file.",
        }

    max_side = max(800, min(int(max_side), 6000))
    max_chars = max(4000, min(int(max_chars), 200_000))

    try:
        img = _pil_open(path)
        img.load()
        img = img.convert("RGB")
        img = _resize_max_side(img, max_side)
        text = _run_ocr(img, psm=6)
        mean_conf = _ocr_confidence_score(img)
    except Exception as e:
        return {
            "error": type(e).__name__,
            "detail": str(e),
            "path": str(path),
            "use_vision_fallback": True,
        }

    text, truncated = _truncate(text, max_chars)
    quality, use_vision = _quality_flags(text, mean_conf)
    if truncated:
        use_vision = True

    compact = _compact_block("ocr_read_image_medium", str(path), text, quality, use_vision)
    return {
        "path": str(path),
        "text": text,
        "level": "medium",
        "mean_confidence": mean_conf,
        "quality": quality,
        "use_vision_fallback": use_vision,
        "truncated": truncated,
        "_model_compact": compact,
    }


def _preprocess_photo(img: Any) -> Any:
    from PIL import Image, ImageOps, ImageFilter, ImageEnhance
    g = img.convert("L")
    g = ImageOps.autocontrast(g, cutoff=3)
    g = g.filter(ImageFilter.MedianFilter(size=3))
    g = ImageEnhance.Sharpness(g).enhance(1.45)
    w, h = g.size
    if min(w, h) < 900:
        scale = 1.65
        g = g.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )
    return g


@tool
def ocr_read_photo_strong(image_path: str, max_side: int = 3600, max_chars: int = 80_000) -> Dict[str, Any]:
    """Уровень 3 (жёсткий): фото с камеры, шум, блики, мелкий шрифт — сильная предобработка + PSM auto.
    Если и это не даёт точный текст — используй multimodal/vision по вложенному изображению."""
    ok, err = _check_tesseract()
    if not ok:
        return {"error": "tesseract_missing", "detail": err, "use_vision_fallback": True}

    path = resolve_abs_path(image_path)
    if not path.is_file():
        return {"error": "not_found", "path": str(path)}

    suf = path.suffix.lower()
    if suf not in _IMAGE_EXT:
        return {"error": "not_an_image", "path": str(path)}

    max_side = max(1200, min(int(max_side), 8000))
    max_chars = max(8000, min(int(max_chars), 250_000))

    try:
        img = _pil_open(path)
        img.load()
        img = img.convert("RGB")
        img = _resize_max_side(img, max_side)
        proc = _preprocess_photo(img)
        text = _run_ocr(proc, psm=3)
        mean_conf = _ocr_confidence_score(proc)
    except Exception as e:
        return {
            "error": type(e).__name__,
            "detail": str(e),
            "path": str(path),
            "use_vision_fallback": True,
        }

    text = re.sub(r"[ \t]+\n", "\n", text)
    text, truncated = _truncate(text, max_chars)
    quality, use_vision = _quality_flags(text, mean_conf, min_chars=10)
    if truncated:
        use_vision = True

    compact = _compact_block("ocr_read_photo_strong", str(path), text, quality, use_vision)
    return {
        "path": str(path),
        "text": text,
        "level": "strong",
        "mean_confidence": mean_conf,
        "quality": quality,
        "use_vision_fallback": use_vision,
        "truncated": truncated,
        "_model_compact": compact,
    }
