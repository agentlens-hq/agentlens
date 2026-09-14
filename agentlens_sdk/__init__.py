"""AgentLens Python SDK."""

from .collector import (
    AgentLensClient,  # kept for backward compat but not advertised
    get_trace_context,
    init,
    load_run,
    load_runs,
    record_memory_snapshot,
    record_tool_result,
    run,
    save_run,
    start_run,
)
from .langgraph import patch_langgraph

__all__ = [
    "AgentLensClient",
    # Public API — use these
    "init",
    "run",
    "patch_langgraph",
    "record_tool_result",
    "record_memory_snapshot",
    "get_trace_context",
    "load_run",
    "load_runs",
    "save_run",
    "start_run",
    # AgentLensClient is a Phase 1 legacy wrapper — kept for backward compat,
    # not advertised. Use agentlens.init() + @agentlens.run() instead.
]
