"""
Task planner for TCA — generates structured plans for complex tasks.
Only creates detailed plans for non-trivial tasks that benefit from planning.
"""
from __future__ import annotations

import json
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage

try:
    from .llm_provider import get_llm
except ImportError:
    from Agent.llm_provider import get_llm


PLANNER_SYSTEM_PROMPT = """You are a task planner for a coding assistant.
Given a user request, return a concise, actionable list of steps (3-10) needed to complete the task.

Rules:
1. Each step should be a single, clear action (e.g., "Create file X with Y functionality")
2. Steps should be in execution order — dependencies first
3. Include testing/verification steps where appropriate
4. Be specific — mention file names, function names, technologies
5. Don't include meta-steps like "understand the request" — jump straight to action

Respond with ONLY a JSON array of strings, no other text. Example:
["Step 1: Create src/auth/handler.py with JWT token validation", "Step 2: Add login endpoint to src/routes/auth.py", "Step 3: Create tests in tests/test_auth.py", "Step 4: Run tests to verify", "Step 5: Update README.md with auth documentation"]
"""


def build_plan(user_task: str) -> List[str]:
    """Call the LLM in planning mode and return a list of steps."""
    if not user_task.strip():
        return []

    llm, _, _ = get_llm("fast")

    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=user_task),
    ]

    try:
        resp = llm.invoke(messages)
    except Exception:
        return _fallback_plan(user_task)

    raw = (resp.content or "").strip()

    # Try parsing as JSON array
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            steps = [str(x).strip() for x in data if str(x).strip()]
            return steps[:12]
    except Exception:
        pass

    # Try extracting JSON from text (model might wrap it in markdown)
    try:
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            data = json.loads(raw[start:end + 1])
            if isinstance(data, list):
                steps = [str(x).strip() for x in data if str(x).strip()]
                return steps[:12]
    except Exception:
        pass

    # Fallback: split by lines/bullets
    lines = [ln.strip("-•* ").strip() for ln in raw.splitlines()]
    steps = [ln for ln in lines if ln and len(ln) > 5]
    if steps:
        return steps[:12]

    return _fallback_plan(user_task)


def _fallback_plan(user_task: str) -> List[str]:
    """Generate a generic plan when LLM planning fails."""
    return [
        f"Step 1: Analyze the request: {user_task[:100]}",
        "Step 2: Read relevant files and understand the codebase",
        "Step 3: Implement the required changes",
        "Step 4: Verify the changes work correctly",
    ]
