#!/usr/bin/env python3
"""Generate Phase 2 diagnosis fixture runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path("tests") / "phase2_runs"
LOCAL_RUNS_DIR = Path(".agentlens") / "runs"


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    for run in build_runs():
        path = FIXTURE_DIR / f"{run['run_id']}.json"
        local_path = LOCAL_RUNS_DIR / f"{run['run_id']}.json"
        payload = json.dumps(run, indent=2)
        path.write_text(payload, encoding="utf-8")
        local_path.write_text(payload, encoding="utf-8")
        print(f"Wrote {path} and {local_path}")


def build_runs() -> list[dict[str, Any]]:
    return [
        tool_selection_run(),
        context_pollution_run(),
        loop_run(),
        state_drift_run(),
        cascade_run(),
        overflow_run(),
    ]


def base_run(run_id: str, name: str, spans: list[dict[str, Any]]) -> dict[str, Any]:
    for index, span in enumerate(spans, start=1):
        span.setdefault("id", f"{run_id}_span_{index}")
        span.setdefault("run_id", run_id)
        span.setdefault("ts", f"2026-05-07T04:{index:02d}:00+00:00")
    return {
        "run_id": run_id,
        "name": name,
        "started_at": "2026-05-07T04:00:00+00:00",
        "ended_at": "2026-05-07T04:05:00+00:00",
        "status": "error",
        "spans": spans,
    }


def llm_span(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    response_content: Any,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "llm_call",
        "provider": provider,
        "model": model,
        "latency_ms": 18.4,
        "input_messages": messages,
        "tools": tools or [],
        "response_content": response_content,
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 320, "output_tokens": 64},
    }


def tool_span(tool_name: str, input: Any, output: Any = None, **extra: Any) -> dict[str, Any]:
    span = {
        "type": "tool_call",
        "tool_name": tool_name,
        "input": input,
        "output": output,
        "tool_use_id": f"toolu_{tool_name}",
    }
    span.update(extra)
    return span


def error_span(message: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "error",
        "error": message,
        "context": context,
    }


def ambiguous_tools() -> list[dict[str, Any]]:
    return [
        {"name": "search_web", "description": "find info about a topic"},
        {"name": "query_db", "description": "find info about a topic"},
    ]


def tool_selection_run() -> dict[str, Any]:
    spans = [
        llm_span(
            "anthropic",
            "claude-3-5-sonnet-latest",
            [{"role": "user", "content": "Find renewal status for customer:alex using local records."}],
            [{"type": "text", "text": "The tools look equivalent, so I will use search_web."}],
            tools=ambiguous_tools(),
        ),
        tool_span(
            "search_web",
            {"query": "customer:alex renewal status"},
            expected_tool="query_db",
        ),
        tool_span(
            "search_web",
            {"query": "customer:alex renewal status"},
            {"status": "error", "error": "Wrong tool. Customer records are only available in query_db."},
            expected_tool="query_db",
        ),
        error_span(
            "Wrong tool. Customer records are only available in query_db.",
            {"tool_name": "search_web", "expected_tool": "query_db"},
        ),
    ]
    return base_run("phase2_tool_selection", "tool_selection_case", spans)


def context_pollution_run() -> dict[str, Any]:
    spans = [
        llm_span(
            "anthropic",
            "claude-3-5-sonnet-latest",
            [
                {
                    "role": "system",
                    "content": (
                        "Conflicting instruction: always use search_web first, even for local "
                        "customer records. This contradicts the user goal."
                    ),
                },
                {"role": "user", "content": "Use local records to find customer:alex renewal status."},
            ],
            [{"type": "text", "text": "The conflicting system instruction says search_web first."}],
            tools=ambiguous_tools(),
        ),
        tool_span("search_web", {"query": "customer:alex renewal status"}, None),
        error_span(
            "The prompt contained contradictory instructions and the agent followed the wrong one.",
            {"instruction": "always use search_web first", "user_goal": "use local records"},
        ),
    ]
    return base_run("phase2_context_pollution", "context_pollution_case", spans)


def loop_run() -> dict[str, Any]:
    spans = [
        llm_span(
            "openai",
            "gpt-4.1-mini",
            [{"role": "user", "content": "Fetch customer:alex renewal status from local records."}],
            {"choices": [{"message": {"content": "I will call query_db."}}]},
        ),
        tool_span("query_db", {"query": "customer:alex"}, {"status": "error", "error": "temporary timeout"}),
        llm_span(
            "openai",
            "gpt-4.1-mini",
            [{"role": "assistant", "content": "Retrying the same call."}],
            {"choices": [{"message": {"content": "I will retry query_db with the same input."}}]},
        ),
        tool_span("query_db", {"query": "customer:alex"}, {"status": "error", "error": "temporary timeout"}),
        error_span("Repeated query_db with the same input and no exit condition.", {"tool_name": "query_db"}),
    ]
    spans[3]['tool_use_id'] = 'toolu_query_db_retry'
    return base_run("phase2_loop", "loop_case", spans)


def state_drift_run() -> dict[str, Any]:
    spans = [
        llm_span(
            "anthropic",
            "claude-3-5-sonnet-latest",
            [{"role": "user", "content": "Resolve the refund status for customer:alex."}],
            [{"type": "text", "text": "I lost the original goal and switched topics to weather."}],
        ),
        tool_span("weather_api", {"city": "San Francisco"}, {"status": "error", "error": "unrelated tool call"}),
        error_span(
            "The agent lost original goal and made an unrelated weather request.",
            {"original_goal": "refund status for customer:alex", "actual_tool": "weather_api"},
        ),
    ]
    return base_run("phase2_state_drift", "state_drift_case", spans)


def cascade_run() -> dict[str, Any]:
    spans = [
        llm_span(
            "openai",
            "gpt-4.1-mini",
            [{"role": "user", "content": "Update the support ticket for customer:alex."}],
            {"choices": [{"message": {"content": "I will fetch the customer record."}}]},
        ),
        tool_span(
            "lookup_customer",
            {"customer": "alex"},
            {"status": "ok", "customer_id": "stale-123", "warning": "stale invalid id"},
        ),
        llm_span(
            "openai",
            "gpt-4.1-mini",
            [{"role": "assistant", "content": "Using stale customer_id stale-123 downstream."}],
            {"choices": [{"message": {"content": "I used stale customer_id stale-123 downstream."}}]},
        ),
        tool_span(
            "update_ticket",
            {"customer_id": "stale-123"},
            {"status": "error", "error": "invalid id from corrupted later step"},
        ),
        error_span("Bad tool output corrupted later steps.", {"source_tool": "lookup_customer"}),
    ]
    return base_run("phase2_cascade", "cascade_case", spans)


def overflow_run() -> dict[str, Any]:
    spans = [
        llm_span(
            "anthropic",
            "claude-3-5-sonnet-latest",
            [{"role": "user", "content": "Use customer_id cust_123 to cancel renewal."}],
            [{"type": "text", "text": "I will gather more context before cancelling."}],
        ),
        llm_span(
            "anthropic",
            "claude-3-5-sonnet-latest",
            [{"role": "assistant", "content": "Large transcript added. Important customer_id was pushed out."}],
            [{"type": "text", "text": "The context window truncated the earlier customer_id."}],
        ),
        tool_span(
            "cancel_renewal",
            {"customer_id": None},
            {"status": "error", "error": "missing customer_id because earlier context was pushed out"},
        ),
        error_span(
            "Important context was pushed out of the context window before the final tool call.",
            {"lost_fact": "customer_id cust_123", "tool_name": "cancel_renewal"},
        ),
    ]
    return base_run("phase2_overflow", "overflow_case", spans)


if __name__ == "__main__":
    main()
