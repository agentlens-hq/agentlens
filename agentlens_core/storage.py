"""Contained identifiers and crash-safe JSON persistence."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

_write_lock = threading.RLock()


def safe_path(directory: Path, run_id: str, suffix: str = '.json') -> Path:
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}', run_id):
        raise ValueError('Invalid run ID: use letters, numbers, underscores or hyphens (no paths).')
    root = directory.resolve()
    result = (root / (run_id + suffix)).resolve()
    if result.parent != root:
        raise ValueError('Run path escapes the storage directory.')
    return result


def atomic_write(path: Path, value: Any) -> None:
    """Readers see a complete old or new snapshot, never a partly written one.

    Shared destinations use last-complete-snapshot semantics, not span merging.
    """
    payload = json.dumps(value, indent=2, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    with _write_lock:
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.run-', suffix='.tmp', delete=False) as handle:
                temporary = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
