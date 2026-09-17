"""Pass-through stream protocols with exactly-once capture finalization."""
from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Callable


class Accumulator:
    def __init__(self, provider: str, api: str):
        self.provider, self.api = provider, api
        self.response: dict[str, Any] = {}
        self.choices: dict[int, dict[str, Any]] = {}
        self.blocks: dict[int, dict[str, Any]] = {}
        self.usage: dict[str, Any] = {}

    def add(self, event: dict[str, Any]) -> None:
        kind = event.get('type', '')
        if self.provider == 'anthropic':
            if kind == 'message_start':
                self.response = event.get('message', {})
                self.usage.update(self.response.get('usage') or {})
            elif kind == 'content_block_start':
                self.blocks[event['index']] = dict(event.get('content_block') or {})
            elif kind == 'content_block_delta':
                block = self.blocks.setdefault(event['index'], {})
                delta = event.get('delta') or {}
                if 'text' in delta:
                    block['text'] = block.get('text', '') + delta['text']
                if 'partial_json' in delta:
                    block['_arguments'] = block.get('_arguments', '') + delta['partial_json']
            elif kind == 'message_delta':
                self.response.update(event.get('delta') or {})
                self.usage.update(event.get('usage') or {})
            return
        if self.api == 'responses':
            if kind in ('response.completed', 'response.incomplete', 'response.failed'):
                self.response = event.get('response') or {}
            elif kind == 'response.output_item.added':
                self.blocks[event.get('output_index', 0)] = dict(event.get('item') or {})
            elif kind == 'response.output_item.done':
                self.blocks[event.get('output_index', 0)] = dict(event.get('item') or {})
            elif kind == 'response.output_text.delta':
                block = self.blocks.setdefault(event.get('output_index', 0), {'type': 'message'})
                block['content'] = block.get('content', [])
                if not block['content']:
                    block['content'] = [{'type': 'output_text', 'text': ''}]
                block['content'][0]['text'] += event.get('delta', '')
            elif kind == 'response.function_call_arguments.delta':
                block = self.blocks.setdefault(event.get('output_index', 0), {'type': 'function_call'})
                block['arguments'] = block.get('arguments', '') + event.get('delta', '')
            return
        self.usage.update(event.get('usage') or {})
        for choice in event.get('choices') or []:
            index = choice.get('index', 0)
            state = self.choices.setdefault(index, {'index': index, 'message': {'role': 'assistant', 'content': ''}, 'finish_reason': None, '_tools': {}})
            delta = choice.get('delta') or {}
            state['message']['content'] += delta.get('content') or ''
            if choice.get('finish_reason'):
                state['finish_reason'] = choice['finish_reason']
            for tool in delta.get('tool_calls') or []:
                target = state['_tools'].setdefault(tool.get('index', 0), {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                if tool.get('id'):
                    target['id'] = tool['id']
                for key in ('name', 'arguments'):
                    target['function'][key] += (tool.get('function') or {}).get(key) or ''

    def result(self) -> dict[str, Any]:
        if self.provider == 'anthropic':
            for block in self.blocks.values():
                if '_arguments' in block:
                    raw = block.pop('_arguments')
                    try:
                        block['input'] = json.loads(raw)
                    except ValueError:
                        block['input'] = raw
            return {**self.response, 'content': list(self.blocks.values()), 'usage': self.usage}
        if self.api == 'responses':
            return self.response or {'output': list(self.blocks.values())}
        choices = []
        for state in self.choices.values():
            tools = state.pop('_tools', {})
            if tools:
                state['message']['tool_calls'] = list(tools.values())
            choices.append(state)
        return {'choices': choices, 'usage': self.usage}


class Stream:
    def __init__(self, raw: Any, provider: str, api: str, encode: Callable, finish: Callable):
        self.raw, self.encode, self.finish = raw, encode, finish
        self.accumulator = Accumulator(provider, api)
        self.iterator = iter(raw)
        self.finished = False

    def _finish(self, status: str, error: BaseException | None = None):
        if not self.finished:
            self.finished = True
            result = self.accumulator.result()
            if status == 'completed' and result.get('status') in ('failed', 'incomplete'):
                status = 'error' if result['status'] == 'failed' else 'partial'
                if status == 'error':
                    error = RuntimeError(str(result.get('error') or 'Provider response failed'))
            if status == 'completed':
                if self.accumulator.provider == 'anthropic':
                    terminal = bool(result.get('stop_reason'))
                elif self.accumulator.api == 'responses':
                    terminal = result.get('status') == 'completed'
                else:
                    choices = result.get('choices') or []
                    terminal = bool(choices) and all(c.get('finish_reason') for c in choices)
                if not terminal:
                    status = 'partial'  # EOF alone is not a provider completion event.
            self.finish(result, status, error)

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self.iterator)
            self.accumulator.add(self.encode(chunk))
            return chunk
        except StopIteration:
            self._finish('completed')
            raise
        except BaseException as exc:
            self._finish('cancelled' if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)) else 'error', exc)
            raise

    def close(self):
        try:
            if hasattr(self.raw, 'close'):
                self.raw.close()
        finally:
            self._finish('partial')

    def __enter__(self):
        return self

    def __exit__(self, kind, exc, tb):
        if exc:
            self._finish('cancelled' if isinstance(exc, asyncio.CancelledError) else 'error', exc)
        self.close()

    def __getattr__(self, name):
        return getattr(self.raw, name)


class AsyncStream(Stream):
    def __init__(self, raw: Any, provider: str, api: str, encode: Callable, finish: Callable):
        self.raw, self.encode, self.finish = raw, encode, finish
        self.accumulator = Accumulator(provider, api)
        self.iterator = raw.__aiter__()
        self.finished = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            chunk = await self.iterator.__anext__()
            self.accumulator.add(self.encode(chunk))
            return chunk
        except StopAsyncIteration:
            self._finish('completed')
            raise
        except BaseException as exc:
            self._finish('cancelled' if isinstance(exc, asyncio.CancelledError) else 'error', exc)
            raise

    async def close(self):
        try:
            if hasattr(self.raw, 'close'):
                result = self.raw.close()
                if inspect.isawaitable(result):
                    await result
        finally:
            self._finish('partial')

    async def __aenter__(self):
        return self

    async def __aexit__(self, kind, exc, tb):
        if exc:
            self._finish('cancelled' if isinstance(exc, asyncio.CancelledError) else 'error', exc)
        await self.close()
