"""Display execution state separately from evidence-based diagnosis state.

A no-failure observation is not a guarantee of semantic correctness.
"""

from __future__ import annotations

from typing import Any

from .diagnose import diagnose_run

# Legacy evidence-strength threshold; not a calibrated probability.
_FAILURE_CONFIDENCE = 0.6

EXECUTION_COMPLETED = "completed"
EXECUTION_ERROR = "error"

DIAGNOSIS_HEALTHY = "healthy"
DIAGNOSIS_FAILURE = "failure_detected"
DIAGNOSIS_UNCERTAIN = "uncertain"
DIAGNOSIS_UNKNOWN = "unknown"


def _execution_status(run: dict[str, Any]) -> str:
    """Preserve incomplete states and translate legacy terminal labels."""
    raw = str(run.get("status") or "").lower()
    return {"success": "completed", "error": "failed", "failure": "failed"}.get(
        raw, raw if raw in {"running", "completed", "failed", "cancelled", "partial"} else "unknown"
    )


def _has_error_span(run: dict[str, Any]) -> bool:
    spans = run.get("spans")
    if not isinstance(spans, list):
        return False
    return any(isinstance(s, dict) and s.get("type") == "error" for s in spans)


def run_status(run: dict[str, Any]) -> dict[str, Any]:
    """Return separated status for a run.

    Returns a dict with:
      execution_status: running | completed | failed | cancelled | partial | unknown
      diagnosis_status: healthy | failure_detected | uncertain | unknown
      root_cause:       category string when failure_detected, else None
      confidence:       diagnosis confidence (0.0 when not computable)
    """
    execution_status = _execution_status(run)

    spans = run.get("spans")
    if not isinstance(spans, list) or not spans:
        # Nothing to diagnose — don't pretend it's healthy.
        return {
            "execution_status": execution_status,
            "diagnosis_status": DIAGNOSIS_UNKNOWN,
            "root_cause": None,
            "confidence": 0.0,
        }

    try:
        diagnosis = diagnose_run(run, use_llm=False)
        confidence = float(diagnosis.get("confidence") or 0.0)
        category = diagnosis.get("root_cause_category")
    except Exception:
        return {
            "execution_status": execution_status,
            "diagnosis_status": DIAGNOSIS_UNKNOWN,
            "root_cause": None,
            "confidence": 0.0,
        }

    has_failure_evidence = execution_status == "failed" or _has_error_span(run)

    if confidence >= _FAILURE_CONFIDENCE:
        diagnosis_status = DIAGNOSIS_FAILURE
        root_cause = category
    elif has_failure_evidence:
        # Something errored, but the heuristics can't confidently categorize it.
        diagnosis_status = DIAGNOSIS_UNCERTAIN
        root_cause = None
    elif execution_status != "completed":
        diagnosis_status = DIAGNOSIS_UNKNOWN
        root_cause = None
    else:
        # Clean completion, no error spans, only the low-confidence default fired.
        diagnosis_status = DIAGNOSIS_HEALTHY
        root_cause = None

    return {
        "execution_status": execution_status,
        "diagnosis_status": diagnosis_status,
        "root_cause": root_cause,
        "confidence": confidence,
    }
