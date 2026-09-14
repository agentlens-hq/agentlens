"""Summarize captured model usage at and after a diagnosed step.

These are historical price-table estimates, not billing data or proof of waste.
"""

from __future__ import annotations

from typing import Any

from agentlens_core.trace import normalize_run


def _span_tokens(span: dict[str, Any]) -> int:
    usage = span.get("usage")
    if not isinstance(usage, dict):
        return 0
    if usage.get("total_tokens"):
        return int(usage["total_tokens"])
    # OpenAI uses prompt/completion; Anthropic uses input/output.
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    return int(prompt) + int(completion)


def compute_impact(spans: list[dict[str, Any]], diagnosis: dict[str, Any]) -> dict[str, Any]:
    """Return token/cost totals and the portion wasted from the failure point on.

    "Wasted" = work spent at or after ``failed_at_step`` — the redundant loop
    iterations, the cascade of corrupted steps, etc. For a healthy run
    (failed_at_step 0) nothing is counted as wasted.
    """
    spans = normalize_run({"spans": spans})["spans"]
    failed_step = int(diagnosis.get("failed_at_step") or 0)
    unknown_cost_calls = sum(s.get("type") == "llm_call" and s.get("cost_usd") is None for s in spans)

    total_tokens = 0
    total_cost = 0.0
    wasted_tokens = 0
    wasted_cost = 0.0
    redundant_tool_calls = 0

    for index, span in enumerate(spans, start=1):
        if not isinstance(span, dict):
            continue
        try:
            tokens = _span_tokens(span) if span.get("type") == "llm_call" else 0
        except (ValueError, TypeError, OverflowError):
            tokens = 0
        cost = float(span.get("cost_usd") or 0.0) if span.get("type") == "llm_call" else 0.0
        total_tokens += tokens
        total_cost += cost
        if failed_step and span.get('original_index', index) >= failed_step:
            wasted_tokens += tokens
            wasted_cost += cost
            if span.get("type") == "tool_call":
                redundant_tool_calls += 1

    return {
        "unknown_cost_calls": unknown_cost_calls,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "wasted_tokens": wasted_tokens,
        "wasted_cost_usd": round(wasted_cost, 6),
        "redundant_tool_calls": redundant_tool_calls,
    }


def impact_summary(impact: dict[str, Any]) -> str:
    """One-line human summary, e.g. for the CLI diagnosis output."""
    wasted_cost = impact.get("wasted_cost_usd", 0.0)
    wasted_tokens = impact.get("wasted_tokens", 0)
    calls = impact.get("redundant_tool_calls", 0)
    if not wasted_tokens and not wasted_cost and not calls:
        return "No post-failure usage measured; this does not prove the run was healthy."
    return (
        f"Post-failure usage: {wasted_tokens} tokens / known subtotal ${wasted_cost:.6f} "
        f"across {calls} tool call(s). Unknown pricing for {impact.get('unknown_cost_calls', 0)} LLM call(s); not proven waste."
    )
