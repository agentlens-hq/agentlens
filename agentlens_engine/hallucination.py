"""Hallucination detector for AgentLens.

Flags three classes of hallucination:
  1. Invented parameters  — tool was called with keys not in its JSON schema.
  2. Missing required     — a required schema field was absent from the tool call.
  3. Context contradiction — LLM response asserts facts that contradict retrieved
                             tool results (numeric mismatches, "not found" vs claimed
                             existence, status field contradictions).
"""

from __future__ import annotations

import re
from typing import Any

from agentlens_core.trace import normalize_run, normalized_tools, text_content

# ── Public API ────────────────────────────────────────────────────────────────

def detect_hallucinations(
    spans: list[dict[str, Any]],
    tool_definitions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return a list of hallucination events found across the span list.

    Each event dict has::

        {
            "type": "invented_param" | "missing_required" | "context_contradiction",
            "step": int,
            "tool_name": str | None,
            "detail": str,
            "confidence": float,   # 0.0–1.0
            "severity": "high" | "medium" | "low",
        }
    """
    spans = normalize_run({"spans": spans})["spans"]
    # Do not apply a later schema revision retroactively to earlier calls.
    has_recorded_schemas = any(s.get('type') == 'llm_call' and s.get('tools') for s in spans)
    schema_map = {} if has_recorded_schemas else _build_schema_map(tool_definitions or [])

    events: list[dict[str, Any]] = []
    tool_outputs: list[dict[str, Any]] = []  # accumulate for contradiction checks

    for i, span in enumerate(spans, start=1):
        if not isinstance(span, dict):
            continue
        i = span.get("original_index", i)
        stype = span.get("type")

        if stype == 'llm_call' and span.get('tools'):
            schema_map.update(_build_schema_map(span['tools']))

        if stype == "tool_call":
            tool_name = span.get("tool_name") or ""
            tool_input = span.get("input")
            schema = schema_map.get(tool_name)

            if schema and isinstance(tool_input, dict):
                events.extend(_check_invented_params(i, tool_name, tool_input, schema))
                events.extend(_check_missing_required(i, tool_name, tool_input, schema))

            tool_output = span.get("output")
            if tool_output is not None:
                tool_outputs.append({"step": i, "tool_name": tool_name, "output": tool_output})

        elif stype == "llm_call":
            resp_content = span.get("response_content")
            resp_text = _extract_text(resp_content)
            if resp_text and tool_outputs:
                events.extend(_check_context_contradiction(i, resp_text, tool_outputs))

    return events


def hallucination_summary(events: list[dict[str, Any]]) -> str:
    """Return a human-readable summary of detected hallucinations."""
    if not events:
        return "No hallucinations detected."
    lines = [f"{len(events)} hallucination(s) detected:"]
    for ev in events:
        sev = ev.get("severity", "?").upper()
        step = ev.get("step", "?")
        etype = ev.get("type", "?").replace("_", " ")
        detail = ev.get("detail", "")
        lines.append(f"  [{sev}] step {step} — {etype}: {detail}")
    return "\n".join(lines)


# ── Schema helpers ────────────────────────────────────────────────────────────

def _build_schema_map(tool_defs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return {tool_name: schema_properties_dict}."""
    result: dict[str, dict[str, Any]] = {}
    for tool in normalized_tools(tool_defs):
        if not isinstance(tool, dict):
            continue
        name = tool.get("name") or (tool.get("function") or {}).get("name")
        if not name:
            continue
        # Anthropic-style: input_schema.properties
        schema = tool.get("input_schema") or {}
        # OpenAI-style: function.parameters.properties
        if not schema and isinstance(tool.get("function"), dict):
            schema = tool["function"].get("parameters") or {}
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        result[str(name)] = {"properties": props, "required": required, "additionalProperties": schema.get("additionalProperties", True), "patternProperties": schema.get("patternProperties", {}), "combinators": any(k in schema for k in ("allOf", "anyOf", "oneOf", "$ref"))}
    return result


# ── Check 1: invented parameters ─────────────────────────────────────────────

def _check_invented_params(
    step: int,
    tool_name: str,
    tool_input: dict[str, Any],
    schema: dict[str, Any],
) -> list[dict[str, Any]]:
    props = set(schema.get("properties", {}).keys())
    if schema.get("additionalProperties") is not False or schema.get("patternProperties") or schema.get("combinators"):
        return []
    extra = [k for k in tool_input if k not in props]
    if not extra:
        return []
    return [
        {
            "type": "invented_param",
            "step": step,
            "tool_name": tool_name,
            "detail": (
                f"'{tool_name}' was called with parameter(s) not in its schema: "
                f"{extra}. Valid params: {sorted(props)}."
            ),
            "confidence": 0.95,
            "severity": "high",
        }
    ]


# ── Check 2: missing required parameters ─────────────────────────────────────

def _check_missing_required(
    step: int,
    tool_name: str,
    tool_input: dict[str, Any],
    schema: dict[str, Any],
) -> list[dict[str, Any]]:
    required = schema.get("required", [])
    if not required:
        return []
    missing = [r for r in required if r not in tool_input]
    if not missing:
        return []
    return [
        {
            "type": "missing_required",
            "step": step,
            "tool_name": tool_name,
            "detail": (
                f"'{tool_name}' was called without required parameter(s): {missing}."
            ),
            "confidence": 0.97,
            "severity": "high",
        }
    ]


# ── Check 3: context contradiction ───────────────────────────────────────────

def _check_context_contradiction(
    step: int,
    resp_text: str,
    tool_outputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # Compare explicit field/value assertions against only the most recent result.
    # Free prose and unrelated numbers do not establish entity correspondence.
    if not tool_outputs:
        return []
    item = tool_outputs[-1]
    output = item["output"]
    if not isinstance(output, dict):
        return []
    events = []
    entities = {k: str(v) for k, v in output.items() if k in ("id", "customer_id", "record_id", "name") and isinstance(v, (str, int))}
    entity_matches = any(re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", resp_text) for v in entities.values())
    for field, observed in output.items():
        if not entity_matches or type(observed) not in (int, float) or field in entities:
            continue
        pattern = r"\b" + re.escape(field) + r"\s*(?:is|=|:)\s*(-?\d+(?:\.\d+)?)\b"
        for match in re.finditer(pattern, resp_text, re.I):
            if float(match.group(1)) != observed:
                events.append({"type": "context_contradiction", "step": step,
                    "tool_name": item["tool_name"], "severity": "medium", "confidence": .8,
                    "detail": f"Step {step} asserts {match.group(0)!r} for the same entity, but tool step {item['step']} returned {field}={observed}.",
                    "evidence": {"source_step": item["step"], "field": field, "observed": observed, "quote": match.group(0)}})
    if entity_matches and output.get("status") == "not_found":
        positive = re.search(r"\b(?:record|customer)\s+(?:(?!\bnot\b)\w+\s+){0,2}(?:was\s+)?found\b", resp_text, re.I)
        if positive and not re.search(r"\bnot\s+found\b", positive.group(0), re.I):
            events.append({"type": "context_contradiction", "step": step, "tool_name": item["tool_name"],
                "severity": "medium", "confidence": .8, "detail": f"Step {step} claims {positive.group(0)!r} for the entity marked not_found at tool step {item['step']}.",
                "evidence": {"source_step": item["step"], "field": "status", "observed": "not_found", "quote": positive.group(0)}})
    return events


def _extract_text(content: Any) -> str:
    return text_content(content)
