"""Каталоги данных и env: префикс ``LORNE_*`` / ``.lorne`` с откатом на ``TCA_*`` / ``.tca``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def env_pref(suffix: str, default: str = "") -> str:
    """Читает ``LORNE_<suffix>``, затем ``TCA_<suffix>`` (совместимость)."""
    lv = os.getenv(f"LORNE_{suffix}")
    if lv is not None and str(lv).strip() != "":
        return str(lv).strip()
    tv = os.getenv(f"TCA_{suffix}")
    if tv is not None and str(tv).strip() != "":
        return str(tv).strip()
    return default


def project_data_dir(cwd: Optional[Path] = None) -> Path:
    """Каталог данных в проекте: ``.lorne`` приоритетно; иначе существующий ``.tca``."""
    root = (cwd or Path.cwd()).resolve()
    newp = root / ".lorne"
    legacy = root / ".tca"
    if newp.exists():
        return newp
    if legacy.exists():
        return legacy
    return newp


def user_config_json_path() -> Path:
    """Глобальный JSON-конфиг: ``~/.lorne_config.json`` или legacy ``~/.tca_config.json``."""
    home = Path.home()
    newp = home / ".lorne_config.json"
    oldp = home / ".tca_config.json"
    if newp.exists():
        return newp
    if oldp.exists():
        return oldp
    return newp


def custom_tools_dir() -> Path:
    """Каталог кастомных тулов: ``~/.lorne_custom_tools`` или legacy."""
    home = Path.home()
    newp = home / ".lorne_custom_tools"
    oldp = home / ".tca_custom_tools"
    if newp.exists():
        return newp
    if oldp.exists():
        return oldp
    return newp


def recent_projects_json_path() -> Path:
    """Недавние проекты: ``~/.lorne_recent_projects.json`` или legacy."""
    home = Path.home()
    newp = home / ".lorne_recent_projects.json"
    oldp = home / ".tca_recent_projects.json"
    if newp.exists():
        return newp
    if oldp.exists():
        return oldp
    return newp
