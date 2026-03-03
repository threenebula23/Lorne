"""Инструмент создания PDF-документа."""
from pathlib import Path
from typing import Any, Dict

from langchain_core.tools import tool

try:
    from ..path_utils import resolve_abs_path
except ImportError:
    def resolve_abs_path(path_str: str) -> Path:
        p = Path(path_str).expanduser()
        return (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()


def _create_pdf_impl(path: Path, title: str, body: str) -> Dict[str, Any]:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import cm
        c = canvas.Canvas(str(path), pagesize=A4)
        c.setFont("Helvetica", 16)
        c.drawString(2 * cm, A4[1] - 2 * cm, title)
        c.setFont("Helvetica", 10)
        y = A4[1] - 3 * cm
        for line in body.replace("\r", "").split("\n"):
            if y < 2 * cm:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = A4[1] - 2 * cm
            c.drawString(2 * cm, y, line[:90])
            y -= 0.5 * cm
        c.save()
        return {"path": str(path), "status": "created"}
    except ImportError:
        # Заглушка: без reportlab пишем текстовый файл с тем же именем и .txt
        txt_path = path.with_suffix(".txt")
        txt_path.write_text(f"# {title}\n\n{body}", encoding="utf-8")
        return {"path": str(txt_path), "status": "created_as_txt", "hint": "Установите reportlab для PDF: pip install reportlab"}


@tool
def create_pdf(filepath: str, title: str, body: str) -> Dict[str, Any]:
    """Создаёт PDF-документ с заданным заголовком и телом. filepath — путь к .pdf файлу."""
    path = resolve_abs_path(filepath)
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    return _create_pdf_impl(path, title, body)
