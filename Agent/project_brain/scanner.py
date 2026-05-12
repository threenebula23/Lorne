"""Static project scan (AST, imports, paths) — no LLM. Output feeds ``build_project_context``."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

_SKIP_DIR_PARTS = frozenset({
    ".venv", "venv", "__pycache__", ".git", "node_modules", ".mypy_cache",
    ".pytest_cache", ".tox", "dist", "build", ".eggs", ".idea",
})

_ENTRY_NAMES = frozenset({"__main__.py", "main.py", "lorne.py", "tca.py", "cli.py"})


def _should_skip(path: Path) -> bool:
    return any(p in _SKIP_DIR_PARTS for p in path.parts)


def _module_id_from_rel(rel: str) -> str:
    s = rel.replace("\\", "/")
    if s.endswith("__init__.py"):
        s = s[: -len("__init__.py")].rstrip("/")
    elif s.endswith(".py"):
        s = s[: -3]
    return s.replace("/", ".").strip(".") or rel


def _import_edges(tree: ast.AST) -> List[str]:
    """Dotted import targets (best-effort) from this file."""
    targets: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                targets.add(node.module)
            elif node.level:
                continue
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    targets.add(alias.name)
    return sorted(targets)


def _api_heuristic(lines: List[str]) -> List[str]:
    hits: List[str] = []
    for i, line in enumerate(lines[:400], 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if re.search(r"\b(FastAPI|APIRouter|@router\.|@app\.(get|post|put|delete|patch)|add_url_rule)\b", s):
            hits.append(f"L{i}: {s[:160]}")
        if len(hits) >= 12:
            break
    return hits


def scan_project(root: Path) -> Dict[str, Any]:
    """Return a JSON-serialisable scan: modules, imports, entrypoints, readme, api hints."""
    root = root.resolve()
    modules: List[Dict[str, Any]] = []
    entrypoints: List[str] = []
    all_py: List[Path] = []

    for py in sorted(root.rglob("*.py")):
        if _should_skip(py):
            continue
        try:
            rel = str(py.relative_to(root))
        except ValueError:
            rel = str(py)
        all_py.append(py)
        if py.name in _ENTRY_NAMES or (py.name == "cli.py" and "Terminal" in rel.replace("\\", "/")):
            entrypoints.append(rel)

    # importer_path -> imported dotted names
    edges: List[Tuple[str, str]] = []

    for py in all_py[:500]:
        if _should_skip(py):
            continue
        try:
            rel = str(py.relative_to(root))
        except ValueError:
            rel = str(py)
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            modules.append({"path": rel, "error": "read_error"})
            continue
        lines = text.splitlines()
        try:
            tree = ast.parse(text, filename=str(py))
        except SyntaxError:
            modules.append(
                {"path": rel, "module_id": _module_id_from_rel(rel), "error": "syntax_error"},
            )
            continue

        funcs: List[Dict[str, str]] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                doc = (ast.get_docstring(node) or "").strip()
                funcs.append(
                    {
                        "name": node.name,
                        "description": (doc[:240] + "…") if len(doc) > 240 else doc,
                    },
                )

        pkg_doc = (ast.get_docstring(tree) or "").strip()
        targets = _import_edges(tree)
        for t in targets:
            edges.append((rel, t))
        mid = _module_id_from_rel(rel)

        modules.append(
            {
                "path": rel,
                "module_id": mid,
                "module_doc": (pkg_doc[:600] + "…") if len(pkg_doc) > 600 else pkg_doc,
                "functions": funcs[:60],
                "imports": sorted({x.split(".")[0] for x in targets if x})[:80],
                "import_targets": targets[:120],
                "api_hints": _api_heuristic(lines),
            },
        )
        if len(modules) >= 400:
            break

    readme_text = ""
    for name in ("README.md", "README.rst", "readme.md"):
        rp = root / name
        if rp.is_file():
            try:
                readme_text = rp.read_text(encoding="utf-8", errors="replace")[:8000]
            except OSError:
                pass
            break

    used_by_map: Dict[str, List[str]] = {}
    for importer, imported in edges:
        used_by_map.setdefault(imported, []).append(importer)

    for m in modules:
        if m.get("error"):
            m["used_by"] = []
            continue
        mid = str(m.get("module_id") or "")
        acc: Set[str] = set()
        for key, imps in used_by_map.items():
            if key == mid or key.startswith(mid + ".") or mid.startswith(key + "."):
                for p in imps:
                    if p != m.get("path"):
                        acc.add(p)
        m["used_by"] = sorted(acc)[:40]

    return {
        "project_name": root.name,
        "root": str(root),
        "modules": modules,
        "entrypoints": sorted(set(entrypoints)),
        "readme_excerpt": readme_text,
    }
