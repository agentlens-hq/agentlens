"""LangGraph integration for AgentLens.

Zero-code-change tracing for LangGraph agents.

Usage::

    import agentlens
    agentlens.init()
    agentlens.patch_langgraph()   # call once before graph.compile()

    from langgraph.graph import StateGraph
    graph = StateGraph(MyState)
    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    ...
    app = graph.compile()         # automatically wrapped by AgentLens

    @agentlens.run(name="my_langgraph_agent")
    def run_agent(input):
        return app.invoke({"messages": input})

Invoke/ainvoke capture aggregate results. Explicit stream_mode="updates" captures
top-level node updates; other stream modes are passed through without node labels.
Compile after patching. Existing compiled graphs and batch are not instrumented.
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Iterator

from .collector import (
    _config,
    _elapsed_ms,
    _now_iso,
    _to_jsonable,
    append_span,
    capture_error,
)


def patch_langgraph() -> bool:
    """Monkeypatch LangGraph's StateGraph.compile() to wrap the compiled graph.

    Returns True if LangGraph was found and patched, False if not installed.
    Call this once after agentlens.init() and before any graph.compile() call.
    """
    try:
        from langgraph.graph.state import StateGraph  # type: ignore[import]
    except ImportError:
        try:
            from langgraph.graph import StateGraph  # type: ignore[import]
        except ImportError:
            return False

    if "langgraph" in _config["patched"]:
        return True

    original_compile = StateGraph.compile

    def patched_compile(self: Any, *args: Any, **kwargs: Any) -> "_AgentLensCompiledGraph":
        compiled = original_compile(self, *args, **kwargs)
        return _AgentLensCompiledGraph(compiled)

    setattr(StateGraph, 'compile', patched_compile)
    _config["patched"].add("langgraph")
    return True


class _AgentLensCompiledGraph:
    """Transparent wrapper around a LangGraph CompiledStateGraph that captures spans."""

    def __init__(self, compiled: Any) -> None:
        self._compiled = compiled

    # ── Sync invoke ──────────────────────────────────────────────────────────

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            result = self._compiled.invoke(input, config=config, **kwargs)
            append_span(
                {
                    "type": "langgraph_run",
                    "provider": "langgraph",
                    "ts": _now_iso(),
                    "latency_ms": _elapsed_ms(started),
                    "input": _to_jsonable(input),
                    "output": _to_jsonable(result),
                    "mode": "invoke",
                }
            )
            return result
        except Exception as exc:
            capture_error(exc, context={"provider": "langgraph", "input": _safe_str(input)})
            raise

    # ── Sync stream ──────────────────────────────────────────────────────────

    def stream(self, input: Any, config: Any = None, **kwargs: Any) -> Iterator[Any]:
        """Stream node outputs — each node's output becomes its own span."""
        started = time.perf_counter()
        nodes_seen: list[str] = []
        try:
            for chunk in self._compiled.stream(input, config=config, **kwargs):
                if kwargs.get('stream_mode') == 'updates' and isinstance(chunk, dict):
                    for node_name, node_output in chunk.items():
                        nodes_seen.append(node_name)
                        append_span(
                            {
                                "type": "langgraph_node",
                                "provider": "langgraph",
                                "ts": _now_iso(),
                                "tool_name": node_name,
                                "input": _to_jsonable(input) if not nodes_seen[:-1] else None,
                                "output": _to_jsonable(node_output),
                                "node_index": len(nodes_seen),
                            }
                        )
                yield chunk
            append_span(
                {
                    "type": "langgraph_run",
                    "provider": "langgraph",
                    "ts": _now_iso(),
                    "latency_ms": _elapsed_ms(started),
                    "input": _to_jsonable(input),
                    "nodes_executed": nodes_seen,
                    "mode": "stream",
                }
            )
        except Exception as exc:
            capture_error(exc, context={"provider": "langgraph", "input": _safe_str(input)})
            raise

    # ── Async invoke ─────────────────────────────────────────────────────────

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            result = await self._compiled.ainvoke(input, config=config, **kwargs)
            append_span(
                {
                    "type": "langgraph_run",
                    "provider": "langgraph",
                    "ts": _now_iso(),
                    "latency_ms": _elapsed_ms(started),
                    "input": _to_jsonable(input),
                    "output": _to_jsonable(result),
                    "mode": "ainvoke",
                    "async": True,
                }
            )
            return result
        except Exception as exc:
            capture_error(exc, context={"provider": "langgraph", "input": _safe_str(input)})
            raise

    # ── Async stream ─────────────────────────────────────────────────────────

    async def astream(self, input: Any, config: Any = None, **kwargs: Any) -> AsyncIterator[Any]:
        """Async stream — each node output becomes its own span."""
        started = time.perf_counter()
        nodes_seen: list[str] = []
        try:
            async for chunk in self._compiled.astream(input, config=config, **kwargs):
                if kwargs.get('stream_mode') == 'updates' and isinstance(chunk, dict):
                    for node_name, node_output in chunk.items():
                        nodes_seen.append(node_name)
                        append_span(
                            {
                                "type": "langgraph_node",
                                "provider": "langgraph",
                                "ts": _now_iso(),
                                "tool_name": node_name,
                                "input": _to_jsonable(input) if not nodes_seen[:-1] else None,
                                "output": _to_jsonable(node_output),
                                "node_index": len(nodes_seen),
                                "async": True,
                            }
                        )
                yield chunk
            append_span(
                {
                    "type": "langgraph_run",
                    "provider": "langgraph",
                    "ts": _now_iso(),
                    "latency_ms": _elapsed_ms(started),
                    "input": _to_jsonable(input),
                    "nodes_executed": nodes_seen,
                    "mode": "astream",
                    "async": True,
                }
            )
        except Exception as exc:
            capture_error(exc, context={"provider": "langgraph", "input": _safe_str(input)})
            raise

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Support direct graph invocation: app(input) as well as app.invoke(input)."""
        return self.invoke(*args, **kwargs)

    def with_config(self, *args: Any, **kwargs: Any) -> '_AgentLensCompiledGraph':
        return _AgentLensCompiledGraph(self._compiled.with_config(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._compiled, name)


def _safe_str(value: Any, max_len: int = 500) -> str:
    try:
        s = str(value)
        return s[:max_len] if len(s) > max_len else s
    except Exception:
        return "<unrepresentable>"
