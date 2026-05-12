"""Deep Solver — пакет (раньше один модуль ``deep_solver.py``).

Имена с ведущим ``_`` не попадают в ``from ._impl_a import *`` (правило
Python), поэтому приватный API, нужный тестам и внешним модулям, реэкспортируем
явно.
"""
from __future__ import annotations

from ._impl_a import *  # noqa: F403
from ._impl_a import (  # noqa: F401
    _DEEP_STATE,
    _build_deep_extra_tools,
    _compact_with_head_lock,
    _extract_facts,
    _filter_tools_for_deep,
    _format_elapsed,
    _render_tool_result,
)
from ._impl_b import *  # noqa: F403
