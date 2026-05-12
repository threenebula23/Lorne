"""Normalize ``scan_project`` output into a Relator-ready context (flat lists + nested dicts)."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _read_project_version(root: Path) -> str:
    pp = root / "pyproject.toml"
    if pp.is_file():
        try:
            txt = pp.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', txt)
            if m:
                return m.group(1)[:48]
        except OSError:
            pass
    pj = root / "package.json"
    if pj.is_file():
        try:
            data = json.loads(pj.read_text(encoding="utf-8", errors="replace"))
            v = data.get("version")
            if isinstance(v, str) and v.strip():
                return v.strip()[:48]
        except Exception:
            pass
    return ""


def _module_bucket(rel: str) -> str:
    p = (rel or "").replace("\\", "/").strip()
    if not p:
        return "code"
    if "/" not in p:
        return "."
    top = p.split("/", 1)[0]
    low = p.lower()
    if "test" in low or top in ("tests", "testing", "test", "__tests__"):
        return "tests"
    return top or "code"


def _layers_from_modules(
    modules_raw: List[Dict[str, Any]], root: Path,
) -> tuple[List[Dict[str, Any]], str]:
    """Layers from top-level paths; second value is a short top-areas summary."""
    counts: Counter[str] = Counter()
    sample_purpose: Dict[str, str] = {}
    for m in modules_raw:
        if m.get("error"):
            continue
        rel = str(m.get("path") or "")
        if not rel:
            continue
        top = _module_bucket(rel)
        counts[top] += 1
        if top not in sample_purpose:
            doc = str(m.get("module_doc") or "").strip()
            sample_purpose[top] = (
                (doc.split("\n")[0][:320]) if doc else f"Sources under `{top}/`."
            )
    if not counts:
        return (
            [
                {
                    "name": root.name or "workspace",
                    "purpose": "Workspace root (no Python modules in scan).",
                    "responsibilities_text": "- Add or include `.py` sources\n- Adjust scan exclusions if needed",
                    "dependencies_text": "- (see manifests in repo root if present)",
                }
            ],
            "",
        )
    layers: List[Dict[str, Any]] = []
    for name, cnt in counts.most_common(12):
        purpose = (sample_purpose.get(name) or f"`{name}/`")[:240]
        layers.append(
            {
                "name": name,
                "purpose": f"{cnt} module(s). {purpose}",
                "responsibilities_text": (
                    f"- Python modules under `{name}/`\n"
                    "- See per-module files in brain `modules/`"
                ),
                "dependencies_text": "- (import graph in module stubs)",
            },
        )
    tops = ", ".join(f"`{k}`" for k, _ in counts.most_common(8))
    return layers, tops


def _module_type(path: str) -> str:
    return _module_bucket(path)


def _readme_first_paragraph(readme: str) -> str:
    if not readme.strip():
        return "See project README for purpose and setup."
    blocks = readme.strip().split("\n\n")
    return (blocks[0] if blocks else readme)[:1200]


def _readme_bullets(readme: str, limit: int = 24) -> List[str]:
    out: List[str] = []
    for line in readme.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ", "• ")):
            out.append(s.lstrip("-*• ").strip()[:200])
        if len(out) >= limit:
            break
    return out or [
        "Source indexed for search (RAG)",
        "Project brain under project_brain/",
        "Edit files in this workspace root",
    ]


def _parse_requirements(root: Path) -> List[Dict[str, str]]:
    req = root / "requirements.txt"
    if not req.is_file():
        return []
    out: List[Dict[str, str]] = []
    try:
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            m = re.match(r"^([a-zA-Z0-9_.\[\]-]+)", s)
            if m:
                name = m.group(1).split("[")[0]
                out.append({"name": name, "spec": s[:120]})
            if len(out) >= 60:
                break
    except OSError:
        pass
    return out


def _stack_from_req(deps: List[Dict[str, str]]) -> List[str]:
    names = [d["name"] for d in deps[:30]]
    if names:
        return names
    return ["(no requirements.txt or empty)"]


def build_project_context(scan: Dict[str, Any], root: Path | None = None) -> Dict[str, Any]:
    """Build the JSON model consumed by Relator templates and ``rag_manifest``."""
    if root is None:
        try:
            from Agent.path_utils import get_project_root

            root = get_project_root().resolve()
        except Exception:
            root = Path.cwd().resolve()
    else:
        root = Path(root).resolve()

    pname = str(scan.get("project_name") or root.name)
    readme = str(scan.get("readme_excerpt") or "")
    modules_raw: List[Dict[str, Any]] = list(scan.get("modules") or [])

    table_modules: List[Dict[str, str]] = []
    rich_modules: List[Dict[str, Any]] = []

    for m in modules_raw:
        if m.get("error"):
            continue
        rel = str(m.get("path") or "")
        mid = str(m.get("module_id") or rel)
        doc = str(m.get("module_doc") or "").strip()
        purpose = doc.split("\n")[0][:400] if doc else f"Python module `{mid}`."
        mtype = _module_type(rel)
        table_modules.append({"name": mid, "purpose": purpose[:200], "type": mtype})

        pub = m.get("functions") or []
        if isinstance(pub, list) and pub and isinstance(pub[0], str):
            pub = [{"name": x.split("(")[0].strip(), "description": x} for x in pub[:40]]
        deps = list(m.get("import_targets") or m.get("imports") or [])
        if isinstance(deps, list) and deps and not isinstance(deps[0], str):
            deps = [str(x) for x in deps]
        rich_modules.append(
            {
                "name": mid,
                "purpose": purpose,
                "responsibilities": [purpose] if purpose else ["See module docstring."],
                "public_api": pub if isinstance(pub, list) else [],
                "dependencies": [str(d) for d in deps[:50]],
                "used_by": [str(u) for u in (m.get("used_by") or [])[:30]],
                "side_effects": (
                    ["May perform I/O when executed"]
                    if "tool" in rel.lower()
                    else ["Import-time side effects unknown"]
                ),
                "risks": [],
                "files": [rel],
                "entrypoints": [rel] if rel in (scan.get("entrypoints") or []) else [],
                "api_hints": m.get("api_hints") or [],
            },
        )

    n_mod = len(table_modules)
    layers, tops = _layers_from_modules(modules_raw, root)
    overview_core = (
        f"Workspace `{pname}` at `{root}`: {n_mod} Python module(s) from static scan."
    )
    overview_text = overview_core + (f" Top-level areas: {tops}." if tops else "")

    req_rows = _parse_requirements(root)
    flows: List[Dict[str, Any]] = [
        {
            "name": "Development loop",
            "description": "Explore codebase → search/read → change → verify.",
            "steps": [
                "Locate relevant modules (list/search/RAG)",
                "Read and cross-check before edits",
                "Apply changes; run tests or checks",
            ],
            "modules": [x["name"] for x in table_modules[:12]],
            "events": [],
            "steps_text": "\n".join(
                f"{i+1}. {s}"
                for i, s in enumerate([
                    "Locate relevant modules (list/search/RAG)",
                    "Read and cross-check before edits",
                    "Apply changes; run tests or checks",
                ])
            ),
            "modules_text": "\n".join(f"- `{n}`" for n in [x["name"] for x in table_modules[:12]]),
        },
    ]

    tools_rows: List[Dict[str, Any]] = [
        {
            "name": "rag_search",
            "type": "retrieval",
            "purpose": "Lexical RAG over indexed sources + Project Brain (high priority).",
            "inputs": ["query", "top_k"],
            "outputs": ["hits with path, snippet, score"],
            "used_by": ["workspace assistant modes with RAG"],
            "inputs_text": "- query\n- top_k",
            "outputs_text": "- hits with path, snippet, score",
            "used_by_text": "- workspace assistant modes with RAG",
        },
        {
            "name": "project_brain_tool",
            "type": "brain",
            "purpose": (
                "Regenerate project_brain from scan (refresh/reindex/scan) or write model Markdown "
                "(write_brain: brain_rel_path + content; write_architecture for agent_architecture.md only)."
            ),
            "inputs": ["action", "brain_rel_path (write_brain)", "content", "write_mode"],
            "outputs": ["written paths", "brain_chunks_indexed", "brain_rel_path on write"],
            "used_by": ["after structural changes or when supplementing brain docs"],
            "inputs_text": "- action\n- brain_rel_path (write_brain)\n- content\n- write_mode",
            "outputs_text": "- written paths\n- brain_chunks_indexed\n- brain_rel_path on write",
            "used_by_text": "- after structural changes or when supplementing brain docs",
        },
        {
            "name": "read_file / edit_file / write_file",
            "type": "filesystem",
            "purpose": "Read and mutate workspace files.",
            "inputs": ["path", "content/lines"],
            "outputs": ["file fragments or confirmations"],
            "used_by": ["full edit modes"],
            "inputs_text": "- path\n- content/lines",
            "outputs_text": "- file fragments or confirmations",
            "used_by_text": "- full edit modes",
        },
    ]

    glossary: List[Dict[str, str]] = [
        {
            "term": "Project Brain",
            "definition": (
                "Generated Markdown under this workspace's project_brain/; "
                "indexed as RAG source=brain."
            ),
        },
        {
            "term": "RAG",
            "definition": "Retrieval-augmented generation over this workspace's files and brain docs.",
        },
    ]

    glossary_lines: List[str] = [
        f"**{g['term']}** — {g['definition']}" for g in glossary
    ]

    ver = _read_project_version(root) or ""

    ctx: Dict[str, Any] = {
        "project_name": pname,
        "project_purpose": _readme_first_paragraph(readme) or overview_text,
        "version": ver,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "modules_count": n_mod,
        "stack": _stack_from_req(req_rows),
        "modules": table_modules,
        "modules_detail": rich_modules,
        "entrypoints": list(scan.get("entrypoints") or []),
        "features": _readme_bullets(readme),
        "constraints": [
            "Do not invent modules or dependencies not present in brain or code.",
            "Prefer rag_search and read_file before large assumptions.",
            "Ask mode: no mutating tools.",
        ],
        "architecture": {
            "overview": overview_text,
            "layers": layers,
            "flows": [],
            "events": [],
        },
        "layers": layers,
        "architecture_overview": overview_text,
        "services": [],
        "agents": [],
        "tools": tools_rows,
        "flows": flows,
        "dependencies": req_rows,
        "glossary": glossary,
        "glossary_lines": glossary_lines,
        "readme_excerpt": readme[:4000],
    }
    return ctx
