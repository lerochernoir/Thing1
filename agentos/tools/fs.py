"""Filesystem helpers scoped to a project workdir."""
from __future__ import annotations

import os
from pathlib import Path


class WorkdirError(Exception):
    pass


class Workspace:
    """Reads/writes files, refusing to escape the configured root."""

    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _resolve(self, rel_path: str) -> Path:
        candidate = (self.root / rel_path).resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise WorkdirError(f"path {rel_path!r} escapes workspace root {self.root}")
        return candidate

    def read(self, rel_path: str) -> str:
        return self._resolve(rel_path).read_text()

    def read_many(self, rel_paths: list[str]) -> dict[str, str]:
        result = {}
        for p in rel_paths:
            path = self._resolve(p)
            if path.exists():
                result[p] = path.read_text()
        return result

    def write(self, rel_path: str, content: str) -> None:
        path = self._resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def delete(self, rel_path: str) -> None:
        path = self._resolve(rel_path)
        if path.exists():
            os.remove(path)

    def exists(self, rel_path: str) -> bool:
        return self._resolve(rel_path).exists()

    def list_files(self, *, ignore_dirs: set[str] | None = None) -> list[str]:
        ignore_dirs = ignore_dirs or {".git", "__pycache__", "node_modules", ".venv", "venv"}
        results = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
            for fname in filenames:
                full = Path(dirpath) / fname
                results.append(str(full.relative_to(self.root)))
        return sorted(results)
