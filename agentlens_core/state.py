"""Compare already-captured JSON state; truncate only the displayed values."""
from __future__ import annotations

import json
from typing import Any


def state_diff(before: Any, after: Any) -> list[dict[str, Any]]:
    """Return JSON-pointer changes. Lists are compared as whole values.

    Values remain local/raw, just like the snapshots. Redact the entire export,
    not individual display strings. Never use truncated values for comparison.
    """
    changes: list[dict[str, Any]] = []

    def visit(old: Any, new: Any, path: str) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                pointer = path + '/' + str(key).replace('~', '~0').replace('/', '~1')
                if key not in old:
                    changes.append({'kind': 'added', 'path': pointer, 'after': new[key]})
                elif key not in new:
                    changes.append({'kind': 'removed', 'path': pointer, 'before': old[key]})
                else:
                    visit(old[key], new[key], pointer)
        elif json.dumps(old, sort_keys=True) != json.dumps(new, sort_keys=True):
            changes.append({'kind': 'changed', 'path': path or '/', 'before': old, 'after': new})

    visit(before, after, '')
    return changes


def format_state_diff(before: Any, after: Any) -> str:
    changes = state_diff(before, after)
    lines = []
    for change in changes:
        values = []
        for key in ('before', 'after'):
            if key in change:
                rendered = json.dumps(change[key], ensure_ascii=True, sort_keys=True)
                values.append(f'{key}={rendered[:200]}' + (' [display truncated]' if len(rendered) > 200 else ''))
        lines.append(f"{change['kind']} {change['path']}: " + ' -> '.join(values))
    return '\n'.join(lines) or 'No recorded state changes.'
