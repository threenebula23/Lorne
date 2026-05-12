"""RAG (Retrieval-Augmented Generation) for Lorne.

Chunking (Python boundaries, Markdown headings), incremental mtime index,
hybrid-style lexical scoring with query normalization and optional multi-query.
Configure with ``LORNE_RAG_*`` (see ``env_pref``).
"""
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from ..file_loading import load_directory_texts
    from ..runtime_paths import env_pref
except ImportError:
    from Agent.file_loading import load_directory_texts
    from Agent.runtime_paths import env_pref

# ─── Index storage ──────────────────────────────────────────────────

_rag_chunks: List[Dict[str, Any]] = []
_file_mtimes: Dict[str, float] = {}
_indexed_root: Optional[str] = None


# ─── Configuration ──────────────────────────────────────────────────

_DEFAULT_PATTERNS = ["*.py", "*.md", "*.ts", "*.tsx", "*.json", "*.yaml", "*.yml"]
_DEFAULT_CHUNK_SIZE = 800
_DEFAULT_CHUNK_OVERLAP = 200
_DEFAULT_MAX_FILES = 500
_MD_HEADER_RE = re.compile(r"^(#{1,4})\s+.+$", re.MULTILINE)


def _patterns_from_env() -> Sequence[str]:
    raw = env_pref("RAG_PATTERNS", "")
    if raw.strip():
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts:
            return parts
    return _DEFAULT_PATTERNS


def _max_files_from_env() -> int:
    raw = env_pref("RAG_MAX_FILES", "")
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


def _chunk_markdown(path: str, text: str,
                    chunk_size: int = _DEFAULT_CHUNK_SIZE,
                    overlap: int = _DEFAULT_CHUNK_OVERLAP) -> List[Dict[str, Any]]:
    """Split Markdown on ``##``-level headings when possible, else line-based."""
    if not text.strip():
        return []
    splits = list(_MD_HEADER_RE.finditer(text))
    if len(splits) < 2:
        return _chunk_text(path, text, chunk_size=chunk_size, overlap=overlap)
    chunks: List[Dict[str, Any]] = []
    preamble = text[: splits[0].start()].strip()
    for i, m in enumerate(splits):
        start = m.start()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
        section = text[start:end].strip()
        if i == 0 and preamble:
            section = (preamble + "\n\n" + section).strip()
        if not section:
            continue
        line0 = text[:start].count("\n")
        sub = _chunk_text(path, section + "\n", chunk_size=max(chunk_size, 400), overlap=overlap)
        for c in sub:
            c["start_line"] = int(c.get("start_line", 0)) + line0
            c["end_line"] = int(c.get("end_line", 0)) + line0
            chunks.append(c)
    return chunks if chunks else _chunk_text(path, text, chunk_size=chunk_size, overlap=overlap)


def _chunk_for_path(path: str, text: str) -> List[Dict[str, Any]]:
    lp = path.lower()
    if lp.endswith(".md") or lp.endswith(".mdx"):
        return _chunk_markdown(path, text)
    return _chunk_text(path, text)


def index_project_brain(root_path: Optional[str] = None) -> int:
    """Index ``<root>/project_brain/**/*.md`` and ``rag_manifest.json`` with ``source=brain``."""
    global _rag_chunks
    if root_path is None or str(root_path).strip() == "":
        try:
            from Agent.path_utils import get_project_root

            root = get_project_root().resolve()
        except Exception:
            root = Path.cwd().resolve()
    else:
        root = Path(root_path).resolve()
    brain_dir = root / "project_brain"
    if not brain_dir.is_dir():
        _rag_chunks = [c for c in _rag_chunks if c.get("source") != "brain"]
        return 0
    rest = [c for c in _rag_chunks if c.get("source") != "brain"]
    add: List[Dict[str, Any]] = []

    def _hint(rel_pb: str) -> str:
        rel_pb = rel_pb.replace("\\", "/")
        if rel_pb.startswith("modules/"):
            return Path(rel_pb).stem
        if rel_pb.startswith("machine/"):
            return Path(rel_pb).stem.replace(".machine", "")
        return ""

    for md in sorted(brain_dir.rglob("*.md")):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(md)
        rel_pb = str(md.relative_to(brain_dir)).replace("\\", "/")
        hint = _hint(rel_pb)
        for c in _chunk_markdown(rel, text):
            c2 = dict(c)
            c2["source"] = "brain"
            if hint:
                c2["module_hint"] = hint
            add.append(c2)

    man = brain_dir / "rag_manifest.json"
    if man.is_file():
        try:
            raw = man.read_text(encoding="utf-8", errors="replace")
        except OSError:
            raw = ""
        for c in _chunk_text(str(man), raw[:24_000]):
            c2 = dict(c)
            c2["source"] = "brain"
            c2["kind"] = "rag_manifest"
            add.append(c2)

    _rag_chunks = rest + add
    return len(add)


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
        for ch in _chunk_for_path(fpath, text):
            ch.setdefault("source", "code")
            new_chunks.append(ch)

    if _indexed_root == root and unchanged_paths:
        # Keep existing chunks for unchanged files, replace changed ones
        brain_kept = [c for c in _rag_chunks if c.get("source") == "brain"]
        kept = [c for c in _rag_chunks if c["path"] in unchanged_paths and c.get("source") != "brain"]
        _rag_chunks = brain_kept + kept + new_chunks
    else:
        brain_kept = [c for c in _rag_chunks if c.get("source") == "brain"]
        _rag_chunks = brain_kept + new_chunks
        _file_mtimes.clear()
        for fpath, _ in all_files:
            try:
                _file_mtimes[fpath] = Path(fpath).stat().st_mtime
            except (FileNotFoundError, OSError):
                pass

    _indexed_root = root
    try:
        index_project_brain(root)
    except Exception:
        pass
    return len(_rag_chunks)


# ─── Search ─────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}", re.IGNORECASE)


def _normalize_query(text: str) -> List[str]:
    """Tokenize query: lowercase alnum tokens, min length 2."""
    raw = (text or "").lower()
    parts = [t.lower() for t in _TOKEN_RE.findall(raw)]
    out: List[str] = []
    seen: set[str] = set()
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _min_score_from_env() -> float:
    raw = env_pref("RAG_MIN_SCORE", "")
    if raw.strip():
        try:
            return max(0.0, float(raw.strip()))
        except ValueError:
            pass
    return 0.35


def _score_chunk(query_words: List[str], full_query: str,
                 chunk: Dict[str, Any], corpus_df: Dict[str, int]) -> float:
    """Lexical score with mild IDF weighting and path / phrase bonuses."""
    text_lower = chunk["text"].lower()
    path_lower = chunk["path"].lower()
    base = Path(chunk["path"]).name.lower()
    n_chunks = max(1, len(_rag_chunks))
    score = 0.0

    for word in query_words:
        if word not in text_lower:
            continue
        count = min(text_lower.count(word), 6)
        df = max(1, int(corpus_df.get(word, 1)))
        idf = math.log((n_chunks + 1) / (df + 1)) + 1.0
        score += count * (len(word) ** 0.5) * idf
        if word in base:
            score += (len(word) + 2) * 2.2
        if word in path_lower and word not in base:
            score += len(word) * 1.2

    fq = full_query.strip().lower()
    if len(fq) >= 4 and fq in text_lower:
        score *= 1.85

    chunk_len = len(chunk["text"])
    if chunk_len > 0 and score > 0:
        score *= 1200.0 / (chunk_len + 400.0)

    return float(score)


def _corpus_doc_freq(chunks: List[Dict[str, Any]], words: List[str]) -> Dict[str, int]:
    df: Dict[str, int] = {w: 0 for w in words}
    for ch in chunks:
        tl = ch["text"].lower()
        for w in words:
            if w in tl:
                df[w] = df.get(w, 0) + 1
    return df


def query(query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Search chunks: **Project Brain first**, then code; lexical + IDF scoring."""
    subs = [s.strip() for s in re.split(r"[;|]\s*", query_text or "") if s.strip()]
    if not subs:
        return []
    all_words: List[str] = []
    for s in subs:
        all_words.extend(_normalize_query(s))
    words = list(dict.fromkeys(all_words))
    if not words:
        return []

    min_sc = _min_score_from_env()

    def _score_pool(chunks: List[Dict[str, Any]]) -> List[Tuple[float, Dict[str, Any]]]:
        if not chunks:
            return []
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for chunk in chunks:
            sc = 0.0
            for sub in subs:
                wsub = _normalize_query(sub)
                if not wsub:
                    continue
                df_sub = _corpus_doc_freq(chunks, wsub)
                sc = max(sc, _score_chunk(wsub, sub.lower(), chunk, df_sub))
            if chunk.get("source") == "brain":
                sc *= 1.42
            if sc >= min_sc:
                scored.append((sc, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    brain_chunks = [c for c in _rag_chunks if c.get("source") == "brain"]
    code_chunks = [c for c in _rag_chunks if c.get("source") != "brain"]
    brain_scored = _score_pool(brain_chunks)
    code_scored = _score_pool(code_chunks)

    ordered: List[Tuple[float, Dict[str, Any]]] = []
    ordered.extend(brain_scored)
    ordered.extend(code_scored)

    results: List[Dict[str, Any]] = []
    seen_paths: Dict[str, int] = {}

    for sc, chunk in ordered:
        path = chunk["path"]
        count = seen_paths.get(path, 0)
        if count >= 3:
            continue
        seen_paths[path] = count + 1

        snippet = chunk["text"].replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"

        row: Dict[str, Any] = {
            "path": path,
            "snippet": snippet,
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "score": round(sc, 3),
            "source": chunk.get("source", "code"),
        }
        if chunk.get("module_hint"):
            row["module_hint"] = chunk["module_hint"]
        results.append(row)
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
        """Поиск RAG: сначала Project Brain (``source=brain``), затем остальной индекс. query — ключевые слова; top_k — число результатов."""
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
