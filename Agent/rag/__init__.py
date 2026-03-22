"""RAG (Retrieval-Augmented Generation) module for TCA.

Features:
- Semantic chunking with overlap (function/class-aware for Python)
- mtime-based caching (incremental reindex)
- Word-level scoring with fuzzy matching
- Configurable via TCA_RAG_PATTERNS and TCA_RAG_MAX_FILES env vars
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from ..file_loading import load_directory_texts
except ImportError:
    from Agent.file_loading import load_directory_texts

# ─── Index storage ──────────────────────────────────────────────────

_rag_chunks: List[Dict[str, Any]] = []
_file_mtimes: Dict[str, float] = {}
_indexed_root: Optional[str] = None


# ─── Configuration ──────────────────────────────────────────────────

_DEFAULT_PATTERNS = ["*.py", "*.md", "*.ts", "*.tsx", "*.json", "*.yaml", "*.yml"]
_DEFAULT_CHUNK_SIZE = 800
_DEFAULT_CHUNK_OVERLAP = 200
_DEFAULT_MAX_FILES = 500


def _patterns_from_env() -> Sequence[str]:
    raw = os.getenv("TCA_RAG_PATTERNS", "")
    if raw.strip():
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts:
            return parts
    return _DEFAULT_PATTERNS


def _max_files_from_env() -> int:
    raw = os.getenv("TCA_RAG_MAX_FILES", "")
    if raw.strip():
        try:
            return int(raw.strip())
        except ValueError:
            pass
    return _DEFAULT_MAX_FILES


# ─── Chunking ───────────────────────────────────────────────────────

_PY_BLOCK_RE = re.compile(r"^(class |def |async def )", re.MULTILINE)


def _chunk_text(path: str, text: str,
                chunk_size: int = _DEFAULT_CHUNK_SIZE,
                overlap: int = _DEFAULT_CHUNK_OVERLAP) -> List[Dict[str, Any]]:
    """Split text into overlapping chunks with line number tracking.

    For Python files, tries to break at function/class boundaries.
    """
    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    is_python = path.endswith(".py")
    chunks: List[Dict[str, Any]] = []
    current_lines: List[str] = []
    current_size = 0
    start_line = 0

    def _emit_chunk():
        if not current_lines:
            return
        chunk_text = "".join(current_lines)
        chunks.append({
            "path": path,
            "text": chunk_text,
            "start_line": start_line,
            "end_line": start_line + len(current_lines) - 1,
        })

    for i, line in enumerate(lines):
        # For Python: break at class/def boundaries if chunk is large enough
        if is_python and current_size > chunk_size // 2 and _PY_BLOCK_RE.match(line):
            _emit_chunk()
            # Keep overlap
            overlap_lines = []
            overlap_size = 0
            for l in reversed(current_lines):
                overlap_lines.insert(0, l)
                overlap_size += len(l)
                if overlap_size >= overlap:
                    break
            current_lines = overlap_lines
            current_size = overlap_size
            start_line = i - len(overlap_lines)

        current_lines.append(line)
        current_size += len(line)

        if current_size >= chunk_size:
            _emit_chunk()
            overlap_lines = []
            overlap_size = 0
            for l in reversed(current_lines):
                overlap_lines.insert(0, l)
                overlap_size += len(l)
                if overlap_size >= overlap:
                    break
            current_lines = overlap_lines
            current_size = overlap_size
            start_line = i - len(overlap_lines) + 1

    _emit_chunk()
    return chunks


# ─── Indexing ───────────────────────────────────────────────────────

def index_documents(root_path: str, pattern: str = "*.py",
                    progress_callback=None) -> int:
    """Index files in root_path with incremental mtime-based caching.

    Args:
        root_path: Root directory to index
        pattern: Glob pattern (if "*.py", uses env patterns instead)
        progress_callback: Optional callable(current, total) for progress display

    Returns:
        Number of indexed chunks
    """
    global _rag_chunks, _indexed_root
    root = str(root_path)
    max_files = _max_files_from_env()

    patterns = [pattern] if pattern and pattern != "*.py" else list(_patterns_from_env())

    all_files: List[Tuple[str, str]] = []
    for pat in patterns:
        part = load_directory_texts(root, pattern=pat, max_size=4 * 1024 * 1024)
        all_files.extend(part)
        if len(all_files) >= max_files:
            all_files = all_files[:max_files]
            break

    # Incremental reindex: only re-chunk files that changed
    new_chunks: List[Dict[str, Any]] = []
    unchanged_paths: set = set()
    total = len(all_files)

    for idx, (fpath, text) in enumerate(all_files):
        if progress_callback:
            progress_callback(idx + 1, total)

        try:
            mtime = Path(fpath).stat().st_mtime
        except (FileNotFoundError, OSError):
            mtime = 0.0

        if (
            _indexed_root == root
            and fpath in _file_mtimes
            and _file_mtimes[fpath] == mtime
        ):
            unchanged_paths.add(fpath)
            continue

        _file_mtimes[fpath] = mtime
        file_chunks = _chunk_text(fpath, text)
        new_chunks.extend(file_chunks)

    if _indexed_root == root and unchanged_paths:
        # Keep existing chunks for unchanged files, replace changed ones
        kept = [c for c in _rag_chunks if c["path"] in unchanged_paths]
        _rag_chunks = kept + new_chunks
    else:
        _rag_chunks = new_chunks
        _file_mtimes.clear()
        for fpath, _ in all_files:
            try:
                _file_mtimes[fpath] = Path(fpath).stat().st_mtime
            except (FileNotFoundError, OSError):
                pass

    _indexed_root = root
    return len(_rag_chunks)


# ─── Search ─────────────────────────────────────────────────────────

def _normalize_query(text: str) -> List[str]:
    """Split query into normalized words for matching."""
    return [w.strip() for w in text.lower().split() if len(w.strip()) >= 2]


def _score_chunk(query_words: List[str], full_query: str,
                 chunk: Dict[str, Any]) -> float:
    """Score a chunk by word match quality."""
    text_lower = chunk["text"].lower()
    path_lower = chunk["path"].lower()
    score = 0.0

    for word in query_words:
        if word in text_lower:
            count = text_lower.count(word)
            score += count * len(word)
        # Bonus for filename match
        if word in path_lower:
            score += len(word) * 3

    # Bonus for exact phrase match
    if full_query in text_lower:
        score *= 2.5

    # Bonus for shorter chunks (more focused)
    chunk_len = len(chunk["text"])
    if chunk_len > 0:
        score = score * (1000 / (chunk_len + 500))

    return score


def query(query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Search indexed chunks with word-level scoring.

    Returns up to top_k results sorted by relevance.
    """
    full_query = query_text.lower().strip()
    words = _normalize_query(query_text)
    if not words:
        return []

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for chunk in _rag_chunks:
        sc = _score_chunk(words, full_query, chunk)
        if sc > 0:
            scored.append((sc, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)

    results: List[Dict[str, Any]] = []
    seen_paths: Dict[str, int] = {}

    for sc, chunk in scored:
        path = chunk["path"]
        # Limit results per file to avoid flooding from one file
        count = seen_paths.get(path, 0)
        if count >= 3:
            continue
        seen_paths[path] = count + 1

        snippet = chunk["text"].replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"

        results.append({
            "path": path,
            "snippet": snippet,
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "score": round(sc, 2),
        })
        if len(results) >= top_k:
            break

    return results


# ─── Stats ──────────────────────────────────────────────────────────

def get_index_stats() -> Dict[str, Any]:
    """Return statistics about the current index."""
    if not _rag_chunks:
        return {"chunks": 0, "files": 0, "root": None}
    unique_files = set(c["path"] for c in _rag_chunks)
    return {
        "chunks": len(_rag_chunks),
        "files": len(unique_files),
        "root": _indexed_root,
    }


# ─── Agent tool ─────────────────────────────────────────────────────

def get_rag_tool():
    """Create a LangChain @tool for the agent to search indexed documents."""
    from langchain_core.tools import tool

    @tool
    def rag_search(query: str, top_k: int = 5) -> Dict[str, Any]:
        """Поиск по индексированным документам проекта (RAG). query — вопрос или ключевые слова; top_k — макс. число результатов."""
        hits = query_fn(query_text=query, top_k=top_k)
        stats = get_index_stats()
        return {
            "query": query,
            "results": hits,
            "index_size": stats["chunks"],
            "files_indexed": stats["files"],
        }

    # Avoid shadowing the module-level `query` function
    query_fn = query
    return rag_search
