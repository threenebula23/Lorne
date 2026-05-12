"""Git integration for Lorne — automatic snapshots and rollback.

Provides auto-commit on file changes (on a dedicated branch ``lorne/auto``),
commit-level rollback, and file history viewing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from git import Repo, InvalidGitRepositoryError, GitCommandError
    HAS_GIT = True
except ImportError:
    HAS_GIT = False
    Repo = None
    InvalidGitRepositoryError = Exception
    GitCommandError = Exception


class GitManager:
    """Manages Git operations for the project directory."""

    LORNE_BRANCH = "lorne/auto"
    TCA_BRANCH = LORNE_BRANCH  # совместимость со старым именем атрибута

    def __init__(self, repo_path: Optional[Path] = None):
        self._repo: Optional[Any] = None
        self._available = False
        if not HAS_GIT:
            return
        path = repo_path or Path.cwd()
        try:
            self._repo = Repo(str(path), search_parent_directories=True)
            self._available = True
        except (InvalidGitRepositoryError, Exception):
            pass

    @property
    def available(self) -> bool:
        return self._available and self._repo is not None

    @property
    def repo(self):
        return self._repo

    # ─── Snapshots ──────────────────────────────────────────────

    def auto_snapshot(self, message: str, files: Optional[List[str]] = None) -> Optional[str]:
        """Create an automatic commit with changed files.

        Args:
            message: Commit message (prefixed with [Lorne])
            files: Specific files to commit, or None for all changes

        Returns:
            Commit hash or None if no changes / not available
        """
        if not self.available:
            return None

        try:
            if files:
                for f in files:
                    try:
                        self._repo.index.add([f])
                    except Exception:
                        pass
            else:
                self._repo.git.add(A=True)

            if not self._repo.index.diff("HEAD") and not self._repo.untracked_files:
                return None

            commit = self._repo.index.commit(f"[Lorne] {message}")
            return str(commit.hexsha)[:10]
        except Exception:
            return None

    # ─── History ────────────────────────────────────────────────

    def log(self, path: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Get commit history.

        Args:
            path: Filter by file path (None = all commits)
            limit: Maximum number of commits to return
        """
        if not self.available:
            return []

        try:
            if path:
                commits = list(self._repo.iter_commits(paths=path, max_count=limit))
            else:
                commits = list(self._repo.iter_commits(max_count=limit))

            return [
                {
                    "hash": str(c.hexsha)[:10],
                    "hash_full": str(c.hexsha),
                    "message": c.message.strip(),
                    "author": str(c.author),
                    "date": c.committed_datetime.isoformat(),
                    "files_changed": len(c.stats.files),
                }
                for c in commits
            ]
        except Exception:
            return []

    # ─── Diff ───────────────────────────────────────────────────

    def diff(self, commit_hash: Optional[str] = None) -> str:
        """Show diff. If commit_hash given, show that commit's diff.
        Otherwise show current unstaged changes.
        """
        if not self.available:
            return "Git не доступен"

        try:
            if commit_hash:
                commit = self._repo.commit(commit_hash)
                if commit.parents:
                    return self._repo.git.diff(commit.parents[0].hexsha, commit.hexsha)
                return self._repo.git.diff(commit.hexsha)
            return self._repo.git.diff()
        except Exception as e:
            return f"Ошибка: {e}"

    # ─── Rollback ───────────────────────────────────────────────

    def rollback_file(self, path: str, commit_hash: Optional[str] = None) -> Dict[str, Any]:
        """Restore a file from a specific commit.

        Args:
            path: File path to restore
            commit_hash: Commit to restore from (None = last commit)
        """
        if not self.available:
            return {"ok": False, "error": "git_not_available"}

        try:
            if commit_hash:
                self._repo.git.checkout(commit_hash, "--", path)
            else:
                self._repo.git.checkout("HEAD", "--", path)
            return {"ok": True, "path": path, "restored_from": commit_hash or "HEAD"}
        except Exception as e:
            return {"ok": False, "error": str(e), "path": path}

    def rollback_commit(self, commit_hash: str) -> Dict[str, Any]:
        """Revert a commit (creates a new revert commit)."""
        if not self.available:
            return {"ok": False, "error": "git_not_available"}

        try:
            self._repo.git.revert(commit_hash, no_edit=True)
            return {"ok": True, "reverted": commit_hash}
        except Exception as e:
            return {"ok": False, "error": str(e), "commit": commit_hash}

    # ─── Branch info ────────────────────────────────────────────

    def current_branch(self) -> str:
        if not self.available:
            return "N/A"
        try:
            return str(self._repo.active_branch)
        except Exception:
            return "detached HEAD"

    def status_summary(self) -> Dict[str, Any]:
        """Get a summary of git status."""
        if not self.available:
            return {"available": False}

        try:
            changed: List[str] = []
            for item in self._repo.index.diff(None):
                p = getattr(item, "a_path", None) or getattr(item, "b_path", None)
                if p:
                    changed.append(str(p))
            staged: List[str] = []
            try:
                for item in self._repo.index.diff("HEAD"):
                    p = getattr(item, "a_path", None) or getattr(item, "b_path", None)
                    if p:
                        staged.append(str(p))
            except Exception:
                try:
                    staged = [str(d.a_path) for d in self._repo.index.diff("HEAD") if getattr(d, "a_path", None)]
                except Exception:
                    staged = []
            untracked = list(self._repo.untracked_files or [])[:50]

            return {
                "available": True,
                "branch": self.current_branch(),
                "changed": changed[:50],
                "staged": staged[:50],
                "untracked": untracked[:50],
                "clean": not changed and not staged and not untracked,
            }
        except Exception as e:
            return {"available": False, "error": str(e)}


# ─── Singleton ──────────────────────────────────────────────────────

_git_manager: Optional[GitManager] = None


def get_git_manager(repo_path: Optional[Path] = None) -> GitManager:
    """Get or create the singleton GitManager."""
    global _git_manager
    if _git_manager is None:
        _git_manager = GitManager(repo_path)
    return _git_manager
