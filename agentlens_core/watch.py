"""Poll atomic run snapshots, not live provider events."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .trace import read_run


class SnapshotWatcher:
    def __init__(self, directory: Path):
        self.directory = directory
        self.seen: dict[Path, tuple[int, int, int, int]] = {}

    def poll(self) -> list[tuple[Path, dict[str, Any] | str]]:
        changed: list[tuple[Path, dict[str, Any] | str]] = []
        paths = set(self.directory.glob('*.json'))
        self.seen = {p: signature for p, signature in self.seen.items() if p in paths}
        for path in sorted(paths):
            try:
                stat = path.stat()
                signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                if self.seen.get(path) == signature:
                    continue
                self.seen[path] = signature
                try:
                    changed.append((path, read_run(path)))
                except ValueError as exc:
                    changed.append((path, str(exc)))
            except FileNotFoundError:
                self.seen.pop(path, None)
        return changed
