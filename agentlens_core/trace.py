"""Provider-neutral trace contracts and validation at untrusted boundaries."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal, TypedDict

ExecutionStatus = Literal['running', 'completed', 'failed', 'cancelled', 'partial', 'unknown']

MAX_RUN_BYTES = 20 * 1024 * 1024


class Span(TypedDict, total=False):
    id: str
    span_id: str
    run_id: str
    original_index: int
    parent_span_id: str
    ts: str
    ended_at: str | None
    metadata: dict[str, Any]
    type: str
    provider: str
    model: str
    status: str
    input_messages: list[dict[str, Any]]
    response_content: Any
    response_text: str
    tools: list[dict[str, Any]]
    tool_name: str
    tool_use_id: str
    input: Any
    output: Any
    completed: bool
    error: Any
    usage: dict[str, Any]
    cost_usd: float | None


class Run(TypedDict, total=False):
    run_id: str
    name: str
    status: str
    started_at: str
    ended_at: str | None
    parent_run_id: str
    spans: list[Span]
    metadata: dict[str, Any]


class Evidence(TypedDict):
    step: int
    field: str
    quote: str


class Diagnosis(TypedDict, total=False):
    root_cause_category: str
    confidence: float
    evidence_strength: str
    failed_at_step: int
    failed_at_tool: str | None
    explanation: str
    fix: str
    evidence: list[Evidence]
    secondary_issues: list[str]


class HallucinationFinding(TypedDict):
    type: str
    step: int
    tool_name: str | None
    detail: str
    confidence: float
    severity: str


def text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ' '.join(filter(None, (text_content(v) for v in value)))
    if isinstance(value, dict):
        for key in ('choices', 'message', 'output', 'content', 'text'):
            if key in value:
                return text_content(value[key])
    return ''


def tool_error(output: Any) -> bool:
    if isinstance(output, str):
        try:
            return tool_error(json.loads(output))
        except (ValueError, RecursionError):
            return output.lower().startswith(('error:', 'error '))
    return isinstance(output, dict) and bool(output.get('error') or output.get('is_error') or output.get('status') in ('error', 'failed'))


def normalized_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    result = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get('function')
        if not isinstance(function, dict):
            function = tool
        if not isinstance(function.get('name'), str):
            continue
        schema = function.get('input_schema') or function.get('parameters') or {}
        if isinstance(schema, dict) and (not isinstance(schema.get('properties', {}), dict) or not isinstance(schema.get('required', []), list)):
            schema = {}
        result.append({'name': function['name'], 'description': str(function.get('description') or ''), 'input_schema': schema if isinstance(schema, dict) else {}})
    return result


def normalize_run(value: Any, strict: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError('Run JSON must be an object.')
    run = dict(value)
    raw = run.get('spans', [])
    if not isinstance(raw, list):
        if strict:
            raise ValueError('Run spans must be an array.')
        raw = []
    spans: list[dict[str, Any]] = []
    ids: dict[str, dict[str, Any]] = {}
    calls: dict[str, dict[str, Any]] = {}
    indices: set[int] = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            if strict:
                raise ValueError(f'Span {index} must be an object.')
            continue
        span = dict(item)
        for field in ('type', 'provider', 'model', 'tool_name', 'tool_use_id', 'span_id', 'id', 'status'):
            if span.get(field) is not None and not isinstance(span[field], str):
                if strict:
                    raise ValueError(f'Span {index}: {field} must be text.')
                span[field] = None
        original = span.get('original_index', index)
        if type(original) is not int or original < 1:
            raise ValueError(f'Span {index} has an invalid original_index.')
        span['original_index'] = original
        span['span_id'] = str(span.get('span_id') or span.get('id') or f'step-{original}')
        span['id'] = span['span_id']
        for field in ('input_messages', 'tools'):
            data = span.get(field)
            if data is not None and not isinstance(data, list):
                # Responses accepts a plain-text input.
                if field == 'input_messages' and isinstance(data, str):
                    span[field] = [{'role': 'user', 'content': data}]
                elif strict:
                    raise ValueError(f'Span {original}: {field} must be an array.')
                else:
                    span[field] = []
            elif isinstance(data, list):
                if strict and any(not isinstance(v, dict) for v in data):
                    raise ValueError(f'Span {original}: malformed {field}.')
                span[field] = [v for v in data if isinstance(v, dict)]
        for message in span.get('input_messages') or []:
            if strict and message.get('role') is not None and not isinstance(message['role'], str):
                raise ValueError(f'Span {original}: message role must be text.')
        for tool in span.get('tools') or []:
            definition = tool.get('function', tool)
            if strict and (not isinstance(definition, dict) or any(definition.get(k) is not None and not isinstance(definition[k], dict) for k in ('parameters', 'input_schema'))):
                raise ValueError(f'Span {original}: tool definition/schema must be an object.')
            if strict and isinstance(definition, dict):
                schema = definition.get('parameters') or definition.get('input_schema') or {}
                if not isinstance(schema.get('properties', {}), dict) or not isinstance(schema.get('required', []), list):
                    raise ValueError(f'Span {original}: invalid tool schema properties/required.')
        usage = span.get('usage')
        if usage is not None and (not isinstance(usage, dict) or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for k, v in usage.items() if k.endswith('tokens') and v is not None)):
            if strict:
                raise ValueError(f'Span {original}: invalid token usage.')
            span['usage'] = {}
        span['tools'] = normalized_tools(span.get('tools'))
        if span.get('type') == 'llm_call':
            span['response_text'] = text_content(span.get('response_content'))
        for field in ('latency_ms', 'cost_usd'):
            number = span.get(field)
            if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or number < 0):
                if strict:
                    raise ValueError(f'Span {original}: invalid {field}.')
                span[field] = None
        if span.get('type') == 'tool_call':
            span.setdefault('completed', span.get('output') is not None)
        existing = ids.get(span['span_id']) or (calls.get(str(span.get('tool_use_id'))) if span.get('type') == 'tool_call' and span.get('tool_use_id') else None)
        if existing is not None:
            if span.get('completed'):
                existing.update({k: v for k, v in span.items() if k not in ('id', 'span_id', 'original_index')})
            continue
        if original in indices:
            raise ValueError(f'Duplicate original_index {original} for different spans.')
        indices.add(original)
        ids[span['span_id']] = span
        if span.get('type') == 'tool_call' and span.get('tool_use_id'):
            calls[str(span['tool_use_id'])] = span
        spans.append(span)
    run['spans'] = spans
    for key in ('run_id', 'name', 'status', 'started_at', 'ended_at', 'parent_run_id'):
        if run.get(key) is not None and not isinstance(run[key], str):
            raise ValueError(f'Run {key} must be a string.')
        if key != 'ended_at' and run.get(key) is None:
            run[key] = 'unknown' if key == 'status' else ''
    return run


def read_run(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_RUN_BYTES:
            raise ValueError('Run exceeds the 20 MiB local input limit; split the run before inspection.')
        value = json.loads(path.read_text(encoding='utf-8'), parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f'Invalid JSON number: {s}')))
        return normalize_run(value, strict=True)
    except (OSError, UnicodeError, RecursionError, ValueError) as exc:
        raise ValueError(f'Cannot read run {path.name}: {exc}') from exc
