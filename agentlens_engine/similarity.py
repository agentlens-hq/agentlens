"""Similar failure search for AgentLens.

Builds a lightweight fingerprint for each diagnosed run and finds historical
runs whose failure pattern best matches a new one.  Works entirely offline —
no embeddings, no external calls.

Fingerprint fields
──────────────────
  category        root_cause_category
  tools           frozenset of tool names that appeared in the run
  failed_tool     the specific tool that failed (or None)
  error_keywords  frozenset of normalised error-signal words
  provider        "anthropic" | "openai" | None
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agentlens_core.trace import normalize_run, read_run

from .diagnose import diagnose_run

# ── Public API ────────────────────────────────────────────────────────────────

def find_similar_failures(
    diagnosis: dict[str, Any],
    target_run: dict[str, Any],
    all_runs: list[dict[str, Any]],
    top_n: int = 5,
    min_score: float = 0.30,
) -> list[dict[str, Any]]:
    """Return the top-N historically similar failed runs.

    Parameters
    ----------
    diagnosis:   diagnosis dict from diagnose_run()
    target_run:  the raw run JSON being diagnosed
    all_runs:    list of all raw run JSONs to search (typically load_runs())
    top_n:       max results to return
    min_score:   minimum similarity score (0–1) to include

    Returns list of::

        {
            "run_id": str,
            "name": str,
            "similarity": float,   # 0–1
            "match_reason": str,
            "category": str,
            "failed_at_tool": str | None,
            "fix": str,
            "started_at": str,
        }
    """
    target_fp = _fingerprint(target_run, diagnosis)
    target_run_id = target_run.get("run_id") or ""

    scored: list[tuple[float, dict[str, Any]]] = []
    for run in all_runs:
        rid = run.get("run_id") or ""
        if rid == target_run_id:
            continue
        # Only compare failed runs
        fp = _fingerprint_from_run(run)
        if fp["category"] == "unknown":
            continue
        score, reason = _score(target_fp, fp)
        if score >= min_score:
            scored.append((score, {"_run": run, "_fp": fp, "_reason": reason, "_score": score}))

    scored.sort(key=lambda t: t[0], reverse=True)

    results = []
    for _, item in scored[:top_n]:
        run = item["_run"]
        fp = item["_fp"]
        results.append(
            {
                "run_id": run.get("run_id") or "",
                "name": run.get("name") or "",
                "similarity": round(item["_score"], 3),
                "match_reason": item["_reason"],
                "category": fp.get("category") or "",
                "failed_at_tool": fp.get("failed_tool"),
                "fix": fp.get("cached_fix") or "",
                "started_at": run.get("started_at") or "",
            }
        )
    return results


def build_failure_library(runs_dir: Path) -> list[dict[str, Any]]:
    """Load all runs from *runs_dir* and return those that have a failure fingerprint."""
    library: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return library
    for path in runs_dir.glob("*.json"):
        try:
            run = read_run(path)
        except (ValueError, OSError):
            continue
        if diagnose_run(run)["root_cause_category"] != "unknown":
            library.append(run)
    return library


# ── Fingerprinting ────────────────────────────────────────────────────────────

def _fingerprint(run: dict[str, Any], diagnosis: dict[str, Any]) -> dict[str, Any]:
    spans = _safe_spans(run)
    tools = frozenset(
        s["tool_name"] for s in spans
        if s.get("type") == "tool_call" and s.get("tool_name")
    )
    providers = {s.get("provider") for s in spans if s.get("type") == "llm_call" and s.get("provider")}
    error_kw = _error_keywords(spans)
    return {
        "category": diagnosis.get("root_cause_category") or "",
        "tools": tools,
        "failed_tool": diagnosis.get("failed_at_tool"),
        "error_keywords": error_kw,
        "provider": next(iter(providers), None),
        "cached_fix": diagnosis.get("fix") or "",
    }


def _fingerprint_from_run(run: dict[str, Any]) -> dict[str, Any]:
    return _fingerprint(run, diagnose_run(run))


def _score(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, str]:
    """Return (similarity_score, reason_string)."""
    score = 0.0
    reasons: list[str] = []

    # Category match — biggest signal
    if a["category"] and a["category"] == b["category"]:
        score += 0.50
        reasons.append(f"same failure category ({a['category']})")

    # Failed tool match
    if a.get("failed_tool") and a["failed_tool"] == b.get("failed_tool"):
        score += 0.20
        reasons.append(f"same failed tool ({a['failed_tool']})")

    # Tool overlap
    ta, tb = a["tools"], b["tools"]
    if ta and tb:
        overlap = len(ta & tb) / max(len(ta | tb), 1)
        score += overlap * 0.15
        if overlap > 0:
            shared = sorted(ta & tb)
            reasons.append(f"shared tools ({', '.join(shared[:3])})")

    # Error keyword overlap
    ka, kb = a["error_keywords"], b["error_keywords"]
    if ka and kb:
        kw_overlap = len(ka & kb) / max(len(ka | kb), 1)
        score += kw_overlap * 0.10
        if kw_overlap > 0:
            shared_kw = sorted(ka & kb)
            reasons.append(f"shared error signals ({', '.join(shared_kw[:3])})")

    # Provider match (minor)
    if a.get("provider") and a["provider"] == b.get("provider"):
        score += 0.05

    reason_str = "; ".join(reasons) if reasons else "weak structural similarity"
    return round(min(score, 1.0), 3), reason_str


# ── Utilities ─────────────────────────────────────────────────────────────────

_ERROR_SIGNAL_WORDS = {
    "error", "failed", "not found", "unavailable", "timeout", "invalid",
    "permission", "refused", "disabled", "only available", "cannot",
    "wrong", "incorrect", "missing", "blocked",
}

_STOP_WORDS = {"the", "a", "an", "is", "in", "at", "to", "of", "and", "or", "for", "was"}


def _error_keywords(spans: list[dict[str, Any]]) -> frozenset[str]:
    words: set[str] = set()
    for span in spans:
        if span.get("type") not in ("error", "tool_call"):
            continue
        texts = [
            _to_str(span.get("error")),
            _to_str(span.get("output")),
            _to_str((span.get("output") or {}).get("error") if isinstance(span.get("output"), dict) else None),
        ]
        for t in texts:
            tokens = set(re.findall(r"\b[a-z]{3,}\b", t.lower()))
            for signal in _ERROR_SIGNAL_WORDS:
                if signal in t.lower():
                    words.add(signal.split()[0])  # normalise multi-word signals
            words.update(tokens - _STOP_WORDS - {"none", "null", "true", "false"})
    # Limit to most diagnostic words
    return frozenset(sorted(words)[:20])


def _safe_spans(run: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_run(run)["spans"]


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)
