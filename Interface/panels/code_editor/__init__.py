"""Панель редактора кода (вкладки, ipynb, поиск)."""

from __future__ import annotations

from ._part_a import (
    CloseWorkspaceTab,
    FileEditorTabPane,
    FileSaved,
    LorneCodeEditor,
    NotebookCellTextArea,
    NotebookContentDirty,
    RunFileRequested,
)
from ._part_b import CodeEditorPanel

__all__ = [
    "CloseWorkspaceTab",
    "CodeEditorPanel",
    "FileEditorTabPane",
    "FileSaved",
    "LorneCodeEditor",
    "NotebookCellTextArea",
    "NotebookContentDirty",
    "RunFileRequested",
]
