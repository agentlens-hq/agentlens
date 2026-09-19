"""Local AgentLens collector and provider monkeypatches."""

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import json
import re
import threading
import time
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

from agentlens_core.privacy import exception_message, redact_credentials
from agentlens_core.storage import atomic_write, safe_path
from agentlens_core.trace import read_run, tool_error

from .pricing import compute_cost_usd

F = TypeVar('F', bound=Callable[..., Any])

RUNS_DIR = Path(".agentlens") / "runs"
_current_run: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "agentlens_current_run", default=None
)
_config: dict[str, Any] = {"api_key": None, "patched": set(), "originals": {}}
_patch_lock = threading.RLock()
_parent_context: contextvars.ContextVar[str | None] = contextvars.ContextVar('agentlens_parent', default=None)


class AmbiguousRunIdError(ValueError):
    """Raised when a run_id prefix matches more than one local run."""

    def __init__(self, prefix: str, matches: list[str]):
        super().__init__(f"Multiple runs match '{prefix}'")
        self.prefix = prefix
        self.matches = matches


class InvalidRunFilesError(ValueError):
    def __init__(self, errors: list[str], runs: list[dict[str, Any]]):
        super().__init__('; '.join(errors))
        self.runs = runs


class AgentLensClient:
    """Backward-compatible direct Anthropic wrapper from the first Phase 1 pass."""

    def __init__(self, api_key: str, client: Any | None = None):
        self._client = client if client is not None else self._build_anthropic_client(api_key)
        self._run = start_run(name="manual")

    def messages_create(self, **kwargs: Any) -> Any:
        # Delegate to the shared proxy so capture logic lives in exactly one place.
        proxy = _AnthropicMessagesProxy(self._client.messages)
        token = _current_run.set(self._run)
        try:
            return proxy.create(**kwargs)
        finally:
            _current_run.reset(token)

    def record_tool_result(
        self, tool_name: str, output: Any, input: Any | None = None, tool_use_id: str | None = None
    ) -> None:
        token = _current_run.set(self._run)
        try:
            record_tool_result(tool_name=tool_name, output=output, input=input, tool_use_id=tool_use_id)
        finally:
            _current_run.reset(token)

    def save_run(self, path: str = "agentlens_run.json") -> None:
        save_run(path=path, run=self._run)

    @property
    def spans(self) -> list[dict[str, Any]]:
        return self._run["spans"]

    @staticmethod
    def _build_anthropic_client(api_key: str) -> Any:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "The anthropic package is required when no client is provided. "
                "Install it or pass a test client into AgentLensClient(..., client=...)."
            ) from exc

        return anthropic.Anthropic(api_key=api_key)


def init(
    api_key: str | None = None,
    parent_context: dict[str, str] | None = None,
) -> None:
    """Enable local capture for supported SDKs already available in this environment.

    Pass ``parent_context=agentlens.get_trace_context()`` from a parent process to
    stitch sub-agent runs into the parent trace.
    """
    _config["api_key"] = api_key
    _parent_context.set(parent_context.get("parent_run_id") if parent_context else None)
    with _patch_lock:
        _patch_providers()


def run(name: str) -> Callable[[F], F]:
    """Group all captured spans inside the decorated function into one saved run."""

    def decorator(func: F) -> F:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                parent = _current_run.get()
                run_data = start_run(name=name, parent_run_id=parent['run_id'] if parent else _parent_context.get())
                token = _current_run.set(run_data)
                try:
                    result = await func(*args, **kwargs)
                    run_data["status"] = "success"
                    return result
                except BaseException as exc:
                    if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                        run_data['status'] = 'cancelled'
                        capture_error(exc, context={'function': func.__name__, 'cancelled': True})
                        raise
                    run_data["status"] = "error"
                    run_data["error"] = exception_message(exc)
                    capture_error(exc, context={"function": func.__name__})
                    raise
                finally:
                    try:
                        _finalize_run(run_data)
                    finally:
                        _current_run.reset(token)

            return cast(F, async_wrapper)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            parent = _current_run.get()
            run_data = start_run(name=name, parent_run_id=parent['run_id'] if parent else _parent_context.get())
            token = _current_run.set(run_data)
            try:
                result = func(*args, **kwargs)
                run_data["status"] = "success"
                return result
            except BaseException as exc:
                if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                    run_data['status'] = 'cancelled'
                    capture_error(exc, context={'function': func.__name__, 'cancelled': True})
                    raise
                run_data["status"] = "error"
                run_data["error"] = exception_message(exc)
                capture_error(exc, context={"function": func.__name__})
                raise
            finally:
                try:
                    _finalize_run(run_data)
                finally:
                    _current_run.reset(token)

        return cast(F, sync_wrapper)

    return decorator


def start_run(name: str = "default", parent_run_id: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "run_id": str(uuid.uuid4()),
        "name": name,
        "started_at": _now_iso(),
        "ended_at": None,
        "status": "running",
        "spans": [],
    }
    if parent_run_id:
        data["parent_run_id"] = parent_run_id
    return data


def get_trace_context() -> dict[str, str] | None:
    """Return a propagation context dict for passing to sub-agents / child runs.

    Usage::

        ctx = agentlens.get_trace_context()
        # pass ctx to the child process / service
        agentlens.init(parent_context=ctx)
    """
    run_data = _current_run.get()
    if run_data is None:
        return None
    return {"parent_run_id": run_data["run_id"]}


def record_memory_snapshot(label: str, state: dict[str, Any]) -> None:
    """Capture a snapshot of the agent's memory / state at the current point in time.

    Usage::

        agentlens.record_memory_snapshot("after_lookup", {"customer": "alex", "status": "active"})
    """
    append_span(
        {
            "type": "memory_snapshot",
            "ts": _now_iso(),
            "label": label,
            "state": _to_jsonable(state),
        }
    )


def current_run() -> dict[str, Any]:
    run_data = _current_run.get()
    if run_data is None:
        run_data = start_run(name="default")
        _current_run.set(run_data)
    return run_data


def append_span(span: dict[str, Any]) -> dict[str, Any]:
    run_data = current_run()
    enriched = redact_credentials({
        **span,
        "id": str(uuid.uuid4()),
        "run_id": run_data["run_id"],
        'original_index': len(run_data['spans']) + 1,
    })
    enriched['span_id'] = enriched['id']
    run_data["spans"].append(enriched)
    return enriched


def _find_tool_span(tool_use_id: str | None) -> dict[str, Any] | None:
    """Return the request span the monkeypatch already recorded for this tool call.

    The provider monkeypatches record a tool_call span with output=None when the
    model *requests* a tool. record_tool_result then carries the *result*. Without
    merging, one logical call produces two spans sharing a tool_use_id, which
    double-counts the (tool, input) signature and makes the classifier mistake a
    single wrong tool choice for a loop. Match on tool_use_id so a genuine loop
    (same tool+input, *different* ids) still produces distinct spans.
    """
    if not tool_use_id:
        return None
    for span in reversed(current_run().get("spans", [])):
        if (
            span.get("type") == "tool_call"
            and span.get("tool_use_id") == tool_use_id
        ):
            return span
    return None


def record_tool_result(
    tool_name: str, output: Any, input: Any | None = None, tool_use_id: str | None = None
) -> None:
    output_json = redact_credentials(_to_jsonable(output))
    existing = _find_tool_span(tool_use_id)
    if existing is not None:
        # Fill the result onto the request span the monkeypatch already recorded.
        existing["output"] = output_json
        existing['completed'] = True
        if input is not None and existing.get("input") in (None, {}):
            existing["input"] = _to_jsonable(input)
        if not existing.get("tool_name"):
            existing["tool_name"] = tool_name
    else:
        append_span(
            {
                "type": "tool_call",
                "ts": _now_iso(),
                "tool_name": tool_name,
                "input": _to_jsonable(input),
                "output": output_json,
                'completed': True,
                "tool_use_id": tool_use_id,
            }
        )
    if _is_error_output(output_json) and not any(s.get('type') == 'error' and s.get('context', {}).get('tool_use_id') == tool_use_id for s in current_run()['spans'] if isinstance(s.get('context', {}), dict)):
        capture_error(
            error=_extract_error_message(output_json),
            context={
                "tool_name": tool_name,
                "input": _to_jsonable(input),
                "output": output_json,
                "tool_use_id": tool_use_id,
            },
        )


def save_run(path: str | None = None, run: dict[str, Any] | None = None) -> Path:
    run_data = run if run is not None else current_run()
    output_path = Path(path) if path else safe_path(RUNS_DIR, run_data['run_id'])
    # Also cover manual saves and fields mutated after initial span capture.
    atomic_write(output_path, redact_credentials(run_data))
    return output_path


def _finalize_run(run_data: dict[str, Any]) -> None:
    if run_data["status"] == "success" and _run_has_error_span(run_data):
        run_data["status"] = "error"
    if run_data['status'] == 'success' and any(s.get('status') == 'partial' or (s.get('type') == 'tool_call' and not s.get('completed', s.get('output') is not None)) for s in run_data['spans']):
        run_data['status'] = 'partial'
    run_data["ended_at"] = _now_iso()
    try:
        save_run(run=run_data)
    except Exception as exc:
        try:
            warnings.warn(f'Run {run_data["run_id"]} could not be persisted ({type(exc).__name__}); agent result is unchanged.', RuntimeWarning)
        except Warning:
            pass  # A warnings-as-errors policy must not replace the agent's result.


def capture_error(error: BaseException | str, context: Any, latency_ms: float | None = None) -> None:
    append_span(
        {
            "type": "error",
            "ts": _now_iso(),
            "step_index": len(current_run()["spans"]) + 1,
            "latency_ms": latency_ms,
            "error": exception_message(error),
            **_error_metadata(error),
            "context": _to_jsonable(context),
        }
    )


def _error_metadata(error: BaseException | str) -> dict[str, Any]:
    metadata: dict[str, Any] = {'error_type': type(error).__name__}
    status = getattr(error, 'status_code', None)
    if type(status) is int and 100 <= status <= 599:
        metadata['status_code'] = status
    request_id = getattr(error, 'request_id', None)
    if isinstance(request_id, str) and re.fullmatch(r'req_[A-Za-z0-9_-]{1,200}', request_id):
        metadata['request_id'] = request_id
    return redact_credentials(metadata)


def capture_tool_results_from_messages(messages: Any, provider: str) -> None:
    run_data = current_run()
    for message in _as_list(messages):
        if _get_value(message, 'role') == 'tool' or _get_value(message, 'type') == 'function_call_output':
            call_id = _get_value(message, 'tool_call_id') or _get_value(message, 'call_id')
            existing = _find_tool_span(call_id)
            if existing is not None and not _tool_result_already_recorded(call_id, run_data):
                output = _get_value(message, 'output') if _get_value(message, 'type') == 'function_call_output' else _get_value(message, 'content')
                record_tool_result(existing['tool_name'], output, tool_use_id=call_id)
            continue
        for block in _as_list(_get_value(message, "content")):
            if _get_value(block, "type") != "tool_result":
                continue
            tool_use_id = _get_value(block, "tool_use_id")
            # The message history accumulates across turns, so this runs over the
            # same tool_result blocks on every subsequent create() call. Skip any
            # tool_use_id we've already recorded a result for, or we append a
            # duplicate span (with input=None) each turn.
            if _tool_result_already_recorded(tool_use_id, run_data):
                continue
            # Anthropic tool_result blocks carry no "name" field — resolve via matching llm_call span
            tool_name = (
                _get_value(block, "name")
                or _resolve_tool_name_from_run(tool_use_id, run_data)
                or provider
            )
            record_tool_result(
                tool_name=tool_name,
                input=None,
                output=_get_value(block, "content"),
                tool_use_id=tool_use_id,
            )
            if _get_value(block, 'is_error'):
                existing = _find_tool_span(tool_use_id)
                if existing is not None:
                    existing['is_error'] = True
                    existing['status'] = 'error'
                capture_error(str(_get_value(block, 'content')), context={'tool_name': tool_name, 'tool_use_id': tool_use_id})


def _tool_result_already_recorded(tool_use_id: str | None, run_data: dict[str, Any]) -> bool:
    """True if a tool_call span for this tool_use_id already has a result recorded."""
    if not tool_use_id:
        return False
    for span in run_data.get("spans", []):
        if (
            span.get("type") == "tool_call"
            and span.get("tool_use_id") == tool_use_id
            and span.get('completed', span.get('output') is not None)
        ):
            return True
    return False


def _resolve_tool_name_from_run(tool_use_id: str | None, run_data: dict[str, Any]) -> str | None:
    """Look backwards through llm_call spans to find the tool name for a given tool_use_id."""
    if not tool_use_id:
        return None
    for span in reversed(run_data.get("spans", [])):
        if span.get("type") != "llm_call":
            continue
        for block in _as_list(span.get("response_content")):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("id") == tool_use_id:
                return block.get("name")
    return None


def capture_anthropic_tool_calls(response_content: Any) -> None:
    for block in _as_list(response_content):
        if _get_value(block, "type") != "tool_use":
            continue
        if _find_tool_span(_get_value(block, 'id')) is not None:
            continue
        append_span(
            {
                "type": "tool_call",
                "ts": _now_iso(),
                "tool_name": _get_value(block, "name"),
                "input": _to_jsonable(_get_value(block, "input")),
                "output": None,
                "tool_use_id": _get_value(block, "id"),
            }
        )


def capture_openai_tool_calls(response: Any) -> None:
    response_json = _to_jsonable(response)

    for tool_call in _find_tool_calls(response_json):
        if _find_tool_span(tool_call.get('id')) is not None:
            continue
        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        append_span(
            {
                "type": "tool_call",
                "ts": _now_iso(),
                "tool_name": function.get("name") or tool_call.get("name"),
                "input": _parse_maybe_json(function.get("arguments") or tool_call.get("input")),
                "output": None,
                "tool_use_id": tool_call.get("id"),
            }
        )


def _patch_providers() -> None:
    import importlib
    patched = []
    resources = [
        ('anthropic.resources.messages', 'Messages', 'anthropic', 'messages', False),
        ('anthropic.resources.messages', 'AsyncMessages', 'anthropic', 'messages', True),
        ('openai.resources.chat.completions', 'Completions', 'openai', 'chat', False),
        ('openai.resources.chat.completions', 'AsyncCompletions', 'openai', 'chat', True),
        ('openai.resources.responses', 'Responses', 'openai', 'responses', False),
        ('openai.resources.responses', 'AsyncResponses', 'openai', 'responses', True),
    ]
    for module, name, provider, api, asynchronous in resources:
        try:
            resource = getattr(importlib.import_module(module), name)
        except (ImportError, AttributeError):
            continue
        _instrument_resource(resource, provider, api, asynchronous)
        patched.append(provider + ':' + api)
    # Small local example clients may have no resource modules.
    for provider, class_name in [('anthropic', 'Anthropic'), ('openai', 'OpenAI')]:
        try:
            provider_module = importlib.import_module(provider)
            cls = getattr(provider_module, class_name)
        except (ImportError, AttributeError):
            continue
        if not any(p.startswith(provider + ':') for p in patched):
            original = cls.__init__
            if not getattr(original, '_agentlens_wrapped', False):
                def initialize(self, *args, _original=original, _provider=provider, **kwargs):
                    _original(self, *args, **kwargs)
                    resource = self.messages if _provider == 'anthropic' else self.chat.completions
                    _instrument_resource(type(resource), _provider, 'messages' if _provider == 'anthropic' else 'chat', False)
                setattr(initialize, '_agentlens_wrapped', True)
                cls.__init__ = initialize
            patched.append(provider)
    _config['patched'].update(patched)
    if not patched:
        warnings.warn('No supported provider SDK is installed; capture is inactive. Install runlens[openai] or runlens[anthropic].', RuntimeWarning)


def _instrument_resource(resource: Any, provider: str, api: str, asynchronous: bool) -> None:
    original = resource.create
    if getattr(original, '_agentlens_wrapped', False):
        return
    if asynchronous:
        @functools.wraps(original)
        async def create(self, *args, **kwargs):
            return await _capture_async(lambda: original(self, *args, **kwargs), kwargs, provider, api)
    else:
        @functools.wraps(original)
        def create(self, *args, **kwargs):
            return _capture_sync(lambda: original(self, *args, **kwargs), kwargs, provider, api)
    setattr(create, '_agentlens_wrapped', True)
    resource.create = create
    if provider == 'anthropic' and hasattr(resource, 'stream'):
        stream = resource.stream
        @functools.wraps(stream)
        def managed(self, *args, **kwargs):
            return _MessageContext(lambda: stream(self, *args, **kwargs), kwargs, asynchronous)
        resource.stream = managed


def _call_context(kwargs: dict[str, Any], provider: str) -> dict[str, Any]:
    result = {'provider': provider, 'model': kwargs.get('model'),
              'input_messages': _to_jsonable(kwargs.get('messages', kwargs.get('input', []))),
              'tools': _to_jsonable(kwargs.get('tools', []))}
    for field in ('system', 'instructions', 'previous_response_id', 'conversation'):
        if field in kwargs:
            result[field] = _to_jsonable(kwargs[field])
    return result


def _begin_call(kwargs: dict[str, Any], provider: str):
    capture_tool_results_from_messages(kwargs.get('messages', kwargs.get('input', [])), provider)
    run_data = current_run()
    context = _call_context(kwargs, provider)
    started, ts = time.perf_counter(), _now_iso()

    def finish(response: Any, status: str = 'completed', error: BaseException | None = None):
        token = _current_run.set(run_data)
        try:
            data = _to_jsonable(response)
            if not isinstance(data, dict):
                data = {}
            usage = data.get('usage') or {}
            span = append_span({
                **context, 'type': 'llm_call', 'ts': ts, 'ended_at': _now_iso(),
                'latency_ms': _elapsed_ms(started), 'status': status,
                'response_content': data.get('content') if provider == 'anthropic' else data,
                'stop_reason': data.get('stop_reason') or data.get('status') or _first_choice_stop_reason(data),
                'usage': usage, 'cost_usd': compute_cost_usd(kwargs.get('model'), usage),
                'streaming': bool(kwargs.get('stream')), 'error': exception_message(error) if error else None,
                **(_error_metadata(error) if error else {}),
            })
            before = len(run_data['spans'])
            if provider == 'anthropic':
                capture_anthropic_tool_calls(data.get('content', []))
            else:
                capture_openai_tool_calls(data)
            for tool_span in run_data['spans'][before:]:
                tool_span['parent_span_id'] = span['span_id']
            if error:
                capture_error(error, context=context, latency_ms=_elapsed_ms(started))
        except Exception as exc:
            warnings.warn(f'Trace capture failed ({type(exc).__name__}); provider result is unchanged.', RuntimeWarning)
        finally:
            _current_run.reset(token)
    return finish


def _capture_sync(call: Callable, kwargs: dict[str, Any], provider: str, api: str):
    from .streams import Stream
    finish = _begin_call(kwargs, provider)
    try:
        response = call()
    except BaseException as exc:
        finish({}, 'cancelled' if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)) else 'error', exc)
        raise
    if kwargs.get('stream'):
        return Stream(response, provider, api, _to_jsonable, finish)
    finish(response)
    return response


async def _capture_async(call: Callable, kwargs: dict[str, Any], provider: str, api: str):
    from .streams import AsyncStream
    finish = _begin_call(kwargs, provider)
    try:
        response = await call()
    except BaseException as exc:
        finish({}, 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'error', exc)
        raise
    if kwargs.get('stream'):
        return AsyncStream(response, provider, api, _to_jsonable, finish)
    finish(response)
    return response


class _MessageContext:
    def __init__(self, factory, kwargs, asynchronous):
        self.manager: Any
        self.stream: Any
        self.factory, self.asynchronous = factory, asynchronous
        self.finish = _begin_call({**kwargs, 'stream': True}, 'anthropic')
        self.manager = None
        self.stream = None

    def __enter__(self):
        try:
            self.manager = self.factory()
            self.stream = self.manager.__enter__()
            return self.stream
        except BaseException as exc:
            self.finish({}, 'error', exc)
            raise

    async def __aenter__(self):
        try:
            self.manager = self.factory()
            self.stream = await self.manager.__aenter__()
            return self.stream
        except BaseException as exc:
            self.finish({}, 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'error', exc)
            raise

    def _finish(self, exc):
        try:
            snapshot = self.stream.current_message_snapshot
        except (RuntimeError, AttributeError):
            snapshot = {}
        status = 'completed' if _get_value(snapshot, 'stop_reason') else 'partial'
        if exc:
            status = 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'error'
        self.finish(snapshot, status, exc)

    def __exit__(self, kind, exc, tb):
        self._finish(exc)
        return self.manager.__exit__(kind, exc, tb)

    async def __aexit__(self, kind, exc, tb):
        self._finish(exc)
        return await self.manager.__aexit__(kind, exc, tb)


class _AnthropicMessagesProxy:
    def __init__(self, messages):
        self.messages = messages

    def create(self, **kwargs):
        if getattr(self.messages.create, '_agentlens_wrapped', False):
            return self.messages.create(**kwargs)
        return _capture_sync(lambda: self.messages.create(**kwargs), kwargs, 'anthropic', 'messages')


def load_runs() -> list[dict[str, Any]]:
    runs = []
    errors = []
    if RUNS_DIR.exists():
        for path in RUNS_DIR.glob('*.json'):
            try:
                runs.append(read_run(safe_path(RUNS_DIR, path.stem)))
            except ValueError as exc:
                errors.append(str(exc))
    runs.sort(key=lambda item: item.get('started_at') or '', reverse=True)
    if errors:
        raise InvalidRunFilesError(errors, runs)
    return runs


def load_run(run_id: str) -> dict[str, Any] | None:
    path = safe_path(RUNS_DIR, run_id)
    if path.exists():
        return read_run(path)
    matches = sorted(p for p in RUNS_DIR.glob('*.json') if p.stem.startswith(run_id))
    if len(matches) > 1:
        raise AmbiguousRunIdError(run_id, [p.stem for p in matches])
    return read_run(safe_path(RUNS_DIR, matches[0].stem)) if matches else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _to_jsonable(value: Any, depth: int = 0) -> Any:
    import dataclasses
    from types import SimpleNamespace
    if depth > 30:
        return '[unsupported nested value]'
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item, depth + 1) for key, item in value.items()}
    if hasattr(value, 'model_dump'):
        return _to_jsonable(value.model_dump(mode='json'), depth + 1)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _to_jsonable(getattr(value, field.name), depth + 1) for field in dataclasses.fields(value)}
    if isinstance(value, SimpleNamespace):
        return _to_jsonable(vars(value), depth + 1)
    return f'<{type(value).__name__}>'


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value is None else [value])


def _get_value(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _is_error_output(output: Any) -> bool:
    return tool_error(output)


def _extract_error_message(output: Any) -> str:
    return str(output.get('error') or output) if isinstance(output, dict) else str(output)


def _parse_maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            pass
    return value


def _find_tool_calls(value: Any) -> list[dict[str, Any]]:
    result = []
    if isinstance(value, dict):
        if value.get('type') == 'function_call':
            result.append({'id': value.get('call_id') or value.get('id'), 'function': {'name': value.get('name'), 'arguments': value.get('arguments')}})
        for key, item in value.items():
            if key == 'tool_calls' and isinstance(item, list):
                result.extend(call for call in item if isinstance(call, dict))
            elif isinstance(item, (dict, list)):
                result.extend(_find_tool_calls(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_find_tool_calls(item))
    ids = set()
    unique = []
    for call in result:
        identity = call.get('id')
        if identity and identity in ids:
            continue
        ids.add(identity)
        unique.append(call)
    return unique


def _first_choice_stop_reason(response: Any) -> Any:
    choices = response.get('choices') if isinstance(response, dict) else None
    return choices[0].get('finish_reason') if isinstance(choices, list) and choices else None


def _run_has_error_span(run_data: dict[str, Any]) -> bool:
    return any(span.get('type') == 'error' for span in run_data.get('spans', []))
