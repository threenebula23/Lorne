from pathlib import Path
from typing import Any, Dict, List, Sequence

try:
    from ..file_loading import load_directory_texts
except ImportError:
    from Agent.file_loading import load_directory_texts

_rag_docs: List[tuple] = []


def _patterns_from_env() -> Sequence[str]:
    """
    Возвращает список шаблонов файлов для индексирования.

    Можно переопределить через переменную окружения TCA_RAG_PATTERNS
    (например: \"*.py,*.md,*.ts,*.tsx,*.json\").
    """
    import os

    raw = os.getenv("TCA_RAG_PATTERNS", "")
    if raw.strip():
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts:
            return parts
    # Значения по умолчанию: код + документация.
    return ["*.py", "*.md", "*.ts", "*.tsx", "*.json"]


def index_documents(root_path: str, pattern: str = "*.py") -> int:
    """
    Индексирует файлы в root_path.

    Если явно указан pattern — используем его, иначе берём набор паттернов
    (Python, markdown, JS/TS и т.д.) и объединяем результаты.
    """
    global _rag_docs
    root = str(root_path)
    if pattern and pattern != "*.py":
        _rag_docs = load_directory_texts(root, pattern=pattern, max_size=2 * 1024 * 1024)
        return len(_rag_docs)

    docs: List[tuple] = []
    for pat in _patterns_from_env():
        part = load_directory_texts(root, pattern=pat, max_size=2 * 1024 * 1024)
        docs.extend(part)
    _rag_docs = docs
    return len(_rag_docs)


def query(query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Простой поиск по подстроке. Возвращает до top_k релевантных фрагментов (путь, текст)."""
    q = query_text.lower()
    results: List[Dict[str, Any]] = []
    for path, text in _rag_docs:
        if q not in text.lower():
            continue
        # Берём кусок вокруг первого вхождения
        idx = text.lower().find(q)
        start = max(0, idx - 200)
        end = min(len(text), idx + 200)
        snippet = text[start:end].replace("\n", " ")
        results.append({"path": path, "snippet": snippet})
        if len(results) >= top_k:
            break
    return results


def get_rag_tool():
    """Инструмент для агента: поиск по индексированным документам."""
    from langchain_core.tools import tool

    @tool
    def rag_search(query: str, top_k: int = 5) -> Dict[str, Any]:
        """Поиск по индексированным документам проекта (RAG). query — вопрос или ключевые слова; top_k — макс. число результатов."""
        hits = query(query_text=query, top_k=top_k)
        return {"query": query, "results": hits, "index_size": len(_rag_docs)}

    return rag_search
