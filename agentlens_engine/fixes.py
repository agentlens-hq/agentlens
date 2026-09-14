"""Actionable fix templates for AgentLens diagnosis categories."""

from __future__ import annotations

from typing import Any


def generate_fix(category: str, compact_run: dict[str, Any], diagnosis: dict[str, Any]) -> str:
    step = diagnosis.get("failed_at_step", 0)
    if category == 'unknown':
        return ''
    tool = diagnosis.get("failed_at_tool") or _first_failed_tool(compact_run) or "the selected tool"
    expected = diagnosis.get('suggested_tool')

    if category == "tool_selection":
        if expected and expected != tool:
            return (
                f"Route this operation to '{expected}' as the error requests; distinguish its supported "
                f"operation from '{tool}' in the tool descriptions and add a routing regression test."
            )
        return (
            f"Rewrite ambiguous tool descriptions and add a routing check before calling '{tool}' "
            "using the operation requirements and the tool's actual supported inputs."
        )

    if category == "loop":
        return (
            f"Add an exit condition that stops retrying '{tool}' after one repeated failure and "
            "forces a different action or a final blocked-state response."
        )

    if category == "context_pollution":
        return (
            f"At original step {step}, remove the conflicting instruction shown in the evidence; keep one explicit priority "
            "rule for the task goal before tool selection."
        )

    if category == "state_drift":
        return (
            f"At original step {step}, restore the original user goal in the next prompt and reject tool calls whose "
            "input no longer matches that goal."
        )

    if category == "cascade":
        return (
            f"Validate the output from '{tool}' before using it downstream; if it is stale, empty, "
            "or malformed, stop and recover instead of feeding it into the next step."
        )

    if category == "overflow":
        return (
            f"Before original step {step}, retain the omitted user facts in a short task summary, then reload it "
            "before making the final tool or answer decision."
        )

    return "Add a guardrail tied to the failed step and rerun the trace to confirm the failure is gone."


def likely_fixes(categories: list[str], compact_run: dict[str, Any]) -> list[str]:
    return [
        generate_fix(category, compact_run, {"root_cause_category": category})
        for category in categories[:2]
    ]


def _first_failed_tool(compact_run: dict[str, Any]) -> str | None:
    for step in compact_run.get("diagnostic_steps", []):
        if step.get("type") == "tool_call" and step.get("tool_name"):
            return step["tool_name"]
    return None
