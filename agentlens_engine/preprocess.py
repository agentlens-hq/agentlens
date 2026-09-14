"""Bound diagnosis input without inventing evidence or renumbering spans."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from agentlens_core.trace import normalize_run, text_content

MAX_STEPS = 200
MAX_TEXT_CHARS = 1000


def _bounded(value: Any, remaining: list[int], depth: int = 0) -> Any:
    if depth > 12 or remaining[0] <= 0:
        return None
    if isinstance(value, str):
        result = value[:min(MAX_TEXT_CHARS, remaining[0])]
        remaining[0] -= len(result)
        return result
    if isinstance(value, list):
        return [_bounded(v, remaining, depth + 1) for v in value[:40] if remaining[0] > 0]
    if isinstance(value, dict):
        return {str(k)[:100]: _bounded(v, remaining, depth + 1) for k, v in list(value.items())[:60] if remaining[0] > 0}
    return value


def preprocess_run(spans: list[dict[str, Any]], run_json: dict[str, Any] | None = None) -> dict[str, Any]:
    run = normalize_run({**(run_json or {}), 'spans': spans})
    normalized = run['spans']
    selected = normalized if len(normalized) <= MAX_STEPS else [normalized[0], *normalized[-(MAX_STEPS - 1):]]
    steps = []
    for span in selected:
        step = _bounded(span, [4000])
        step['step'] = span['original_index']
        step['original_index'] = span['original_index']
        step['span_id'] = span['span_id']
        step['type'] = span.get('type')
        step['response_text'] = text_content(step.get('response_text'))
        step['input_messages'] = step.get('input_messages') or []
        step['tools'] = step.get('tools') or []
        for key in ('input', 'output'):
            step[key + '_digest'] = hashlib.sha256(json.dumps(span.get(key), sort_keys=True, default=str).encode()).hexdigest()
        steps.append(step)
    tools = {}
    for span in normalized:
        for tool in span.get('tools', []):
            tools[tool['name']] = tool
    errors = [s for s in steps if s.get('type') == 'error']
    warnings = []
    if len(normalized) > MAX_STEPS:
        warnings.append('earlier spans omitted by preprocessing')
    if not normalized:
        warnings.append('no usable spans')
    if run.get('status') in ('running', 'partial', 'cancelled'):
        warnings.append('incomplete execution')
    return {
        'run_id': run.get('run_id'), 'status': run.get('status'),
        'system_prompt': _bounded(_find_system_prompt(normalized), [2000]),
        'tool_definitions': _bounded(list(tools.values()), [4000]),
        'diagnostic_steps': steps,
        'final_output': next((s.get('response_content') for s in reversed(steps) if s.get('type') == 'llm_call'), None),
        'failure_step_hint': errors[0]['step'] if errors else 0,
        'trace_warnings': warnings,
    }


def _find_system_prompt(spans: list[dict[str, Any]]) -> str | None:
    for span in spans:
        if span.get('system') or span.get('instructions'):
            return text_content(span.get('system') or span.get('instructions'))
        for message in span.get('input_messages') or []:
            if message.get('role') in ('system', 'developer'):
                return text_content(message.get('content'))
    return None


_response_text = text_content
