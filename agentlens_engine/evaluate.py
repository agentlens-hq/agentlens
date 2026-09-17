"""Simple local diagnosis evaluation for fixture and real-world cases."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agentlens_core.trace import read_run

from .classifier import FAILURE_CATEGORIES
from .diagnose import diagnose_run

FIXTURE_EXPECTED = {
    "phase2_tool_selection": ("tool_selection", 2),
    "phase2_context_pollution": ("context_pollution", 1),
    "phase2_loop": ("loop", 2),
    "phase2_state_drift": ("state_drift", 1),
    "phase2_cascade": ("cascade", 2),
    "phase2_overflow": ("overflow", 2),
}


def evaluate_cases(
    fixture_dir: Path | None = None,
    real_world_dir: Path | None = None,
) -> dict[str, Any]:
    if fixture_dir is None:
        fixture_dir = Path(__file__).parent / "corpus" / "positive"
    if real_world_dir is None:
        real_world_dir = Path.cwd() / "real_world_cases"
    results: list[dict[str, Any]] = []
    results.extend(_evaluate_directory(fixture_dir, FIXTURE_EXPECTED, source="fixture"))
    results.extend(_evaluate_directory(Path(__file__).parent / "corpus" / "healthy", {}, source="healthy"))
    results.extend(_evaluate_directory(real_world_dir, {}, source="real_world"))
    return _summarize(results)


def print_evaluation(report: dict[str, Any]) -> None:
    print("AgentLens Diagnosis Evaluation")
    print()
    print("Offline rule evaluation; small regression corpus, not a population accuracy estimate.")
    print(f"Total cases: {report['total_cases']}")
    print(f"Positive / healthy-or-incomplete controls: {report['positive_cases']} / {report['healthy_cases']}")
    print(f"Errors / unscored cases: {report['case_errors']} / {report['unscored_cases']}")
    print(f"False positives / false negatives: {report['false_positives']} / {report['false_negatives']}")
    print(f"Category / original-step matches: {report['category_matches']} / {report['step_matches']} of {report['scored_cases']}")
    print(f"Category / original-step mismatches: {report['category_mismatches']} / {report['step_mismatches']}")
    print(f"Confident-wrong (>= 0.80): {report['confident_wrong']}/{report['high_confidence_cases']} scored high-confidence diagnoses")
    print(f"Abstentions: {report['abstentions']} / {report['total_cases']}")
    print(f"Diagnosed failures: {report['diagnosed_failure_cases']} / {report['diagnosed_cases']} returned diagnoses")
    print(f"Negative/control execution statuses (not correctness claims): {report['control_statuses']}")
    print(f"Fixture cases: {report['fixture_cases']}")
    print(f"Fixture accuracy: {report['fixture_accuracy']:.0%}")
    print(f"Saved cases: {report['real_world_cases']} (folder name does not establish external provenance)")
    print(f"Saved scored cases: {report['real_world_scored_cases']}")
    for population, counts in report['populations'].items():
        print(f"{population}: {counts['total']} cases; correct={counts['correct']}, partial={counts['partial']}, "
              f"wrong={counts['wrong']}, abstained={counts['abstained']}, errors={counts['errors']}, unscored={counts['unscored']}")
        denominator = counts['high_confidence']
        rate = f"{counts['high_confidence_wrong'] / denominator:.0%}" if denominator else 'unmeasured'
        print(f"  High-confidence correct: {counts['high_confidence_correct']}/{denominator}; "
              f"confident-wrong: {counts['high_confidence_wrong']}/{denominator} ({rate})")
    print(f"Low-confidence rate: {report['low_confidence_rate']:.0%} ({report['low_confidence_cases']}/{report['diagnosed_cases']} returned diagnoses)")
    print(f"Average runtime: {report['average_latency_ms']:.2f} ms")
    print(f"Most failed category: {report['most_failed_category']}")
    print(f"False-positive rate: {report['false_positives']}/{report['healthy_cases']}")
    print(f"False-negative rate: {report['false_negatives']}/{report['positive_cases']}")
    print("Provider/framework groups (regression labels, not live validation):")
    for group, counts in sorted(report['provider_breakdown'].items()):
        print(f"- {group}: {counts['correct']}/{counts['total']} matched")
    print()
    print("Fixture accuracy by category:")
    for category, accuracy in sorted(report["accuracy_by_category"].items()):
        print(f"- {category}: {accuracy:.0%}")
    if report["real_world_accuracy_by_category"]:
        print()
        print("Saved-case label matches by category (not user accuracy):")
        for category, accuracy in sorted(report["real_world_accuracy_by_category"].items()):
            print(f"- {category}: {accuracy:.0%}")
    if report["unscored_real_world_cases"]:
        print()
        print("Unscored saved cases:")
        for case in report["unscored_real_world_cases"]:
            print(f"- {case}")
    for result in report["results"]:
        if result.get("error"):
            print(f"ERROR {result['path']}: {result['error']}")


def _evaluate_directory(
    directory: Path, expected: dict[str, tuple[str, int]], source: str
) -> list[dict[str, Any]]:
    if not directory.exists():
        return []

    results = []
    for path in sorted(directory.rglob("*.json")):
        if path.name in {"actual_diagnosis.json", "expected_diagnosis.json", "diagnosis.json"}:
            continue
        row: dict[str, Any] = {
            "source": source, "provider_group": "unspecified", "path": str(path),
            "run_id": path.stem, "expected_category": None, "expected_step": None,
            "actual_category": None, "actual_step": None, "confidence": None,
            "scored": False, "correct": False,
            "population": "regression" if source != "real_world" else "unclassified",
        }
        started = time.perf_counter()
        try:
            run = read_run(path)
            row["run_id"] = str(run.get("run_id") or path.stem)
            row["execution_status"] = run.get("status", "unknown")
            if source == 'real_world':
                provenance = run.get('evaluation_population')
                expected_path = path.parent / 'expected_diagnosis.json'
                if provenance is None and expected_path.exists():
                    provenance = (_load_json(expected_path) or {}).get('evaluation_population')
                if provenance is not None:
                    if provenance not in ('regression', 'internal_natural', 'external_developer'):
                        raise ValueError('Invalid evaluation_population in run or expectation')
                    row['population'] = provenance
            category, step = _expected_for(run, expected.get(row["run_id"]), path.parent / "expected_diagnosis.json")
            row.update(expected_category=category, expected_step=step, scored=category is not None)
            row["provider_group"] = '/'.join(sorted({str(s.get('provider')) for s in run['spans'] if s.get('provider')})) or 'unspecified'
            diagnosis = diagnose_run(run, use_llm=False)
            row.update(actual_category=diagnosis["root_cause_category"], actual_step=diagnosis["failed_at_step"], confidence=diagnosis["confidence"])
            row["correct"] = row["scored"] and row["actual_category"] == category and row["actual_step"] == step
        except Exception as exc:
            # A failed case remains in the report and makes CLI verification fail.
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["latency_ms"] = (time.perf_counter() - started) * 1000
        results.append(row)
    return results


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [result for result in results if result["scored"]]
    fixture = [result for result in results if result["source"] == "fixture"]
    real_world = [result for result in results if result["source"] == "real_world"]
    fixture_scored = [result for result in fixture if result["scored"]]
    real_world_scored = [result for result in real_world if result["scored"]]
    diagnosed = [result for result in results if result["confidence"] is not None]
    low_confidence = [result for result in diagnosed if result["confidence"] < 0.6]
    high_confidence = [result for result in scored if result["confidence"] is not None and result["confidence"] >= 0.8]
    latency_values = [result["latency_ms"] for result in results]
    by_category: dict[str, list[bool]] = {}
    real_by_category: dict[str, list[bool]] = {}
    failed_categories: dict[str, int] = {}
    provider_breakdown: dict[str, dict[str, int]] = {}
    control_statuses: dict[str, int] = {}
    for result in results:
        if result["expected_category"] == "unknown":
            status = result.get("execution_status", "unknown")
            control_statuses[status] = control_statuses.get(status, 0) + 1
    for result in scored:
        group = provider_breakdown.setdefault(result['provider_group'], {'correct': 0, 'total': 0})
        group['total'] += 1
        group['correct'] += int(result['correct'])
    for result in fixture_scored:
        by_category.setdefault(result["expected_category"], []).append(result["correct"])
    for result in real_world_scored:
        real_by_category.setdefault(result["expected_category"], []).append(result["correct"])
    for result in scored:
        if not result["correct"]:
            category = result["expected_category"] or result["actual_category"]
            failed_categories[category] = failed_categories.get(category, 0) + 1

    return {
        "results": results,
        "populations": {
            population: _trust_metrics([r for r in results if r.get('population', 'unclassified') == population])
            for population in ('regression', 'internal_natural', 'external_developer', 'unclassified')
        },
        "provider_breakdown": provider_breakdown,
        "control_statuses": control_statuses,
        "diagnosed_cases": len(diagnosed),
        "diagnosed_failure_cases": sum(r["actual_category"] not in (None, "unknown") for r in results),
        "low_confidence_cases": len(low_confidence),
        "positive_cases": sum(r["expected_category"] not in (None, "unknown") for r in results),
        "healthy_cases": sum(r["expected_category"] == "unknown" for r in results),
        "false_positives": sum(r["expected_category"] == "unknown" and r["actual_category"] not in (None, "unknown") for r in results),
        "false_negatives": sum(r["expected_category"] not in (None, "unknown") and r["actual_category"] == "unknown" for r in results),
        "category_matches": sum(r["scored"] and r["expected_category"] == r["actual_category"] for r in results),
        "step_matches": sum(r["scored"] and r["expected_step"] == r["actual_step"] for r in results),
        "category_mismatches": sum(r["expected_category"] != r["actual_category"] for r in scored),
        "step_mismatches": sum(r["expected_step"] != r["actual_step"] for r in scored),
        "case_errors": sum(bool(r.get("error")) for r in results),
        "unscored_cases": len(results) - len(scored),
        "high_confidence_cases": len(high_confidence),
        "confident_wrong": sum(not r["correct"] for r in high_confidence),
        "abstentions": sum(r["actual_category"] == "unknown" for r in results),
        "total_cases": len(results),
        "scored_cases": len(scored),
        "overall_accuracy": _rate([result["correct"] for result in scored]),
        "fixture_cases": len(fixture),
        "fixture_accuracy": _rate([result["correct"] for result in fixture_scored]),
        "real_world_cases": len(real_world),
        "real_world_scored_cases": len(real_world_scored),
        "real_world_accuracy": _rate([result["correct"] for result in real_world_scored]),
        "low_confidence_rate": len(low_confidence) / len(diagnosed) if diagnosed else 0.0,
        "average_latency_ms": sum(latency_values) / len(latency_values) if latency_values else 0.0,
        "most_failed_category": _most_failed_category(failed_categories),
        "accuracy_by_category": {
            category: _rate(values) for category, values in by_category.items()
        },
        "real_world_accuracy_by_category": {
            category: _rate(values) for category, values in real_by_category.items()
        },
        "unscored_real_world_cases": [
            result["path"]
            for result in results
            if result["source"] == "real_world" and not result["scored"]
        ],
    }


def _trust_metrics(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Mutually exclusive scored outcomes; an expected abstention stays abstained.

    Partial means category matched but original step did not. This is not a
    judgment of usefulness. Provenance/outcomes require independent human review.
    """
    judged = [r for r in rows if r['scored'] and not r.get('error')]
    diagnosed = [r for r in judged if r['actual_category'] not in (None, 'unknown')]
    high = [r for r in diagnosed if r['confidence'] is not None and r['confidence'] >= .8]
    return {
        'total': len(rows),
        'failure_cases': sum(r['expected_category'] not in (None, 'unknown') for r in rows),
        'correct': sum(bool(r['correct']) for r in diagnosed),
        'partial': sum(not r['correct'] and r['actual_category'] == r['expected_category'] for r in diagnosed),
        'wrong': sum(r['actual_category'] != r['expected_category'] for r in diagnosed),
        'abstained': sum(r['actual_category'] == 'unknown' for r in judged),
        'correct_abstentions': sum(r['actual_category'] == 'unknown' and r['correct'] for r in judged),
        'errors': sum(bool(r.get('error')) for r in rows),
        'unscored': sum(not r['scored'] for r in rows),
        'high_confidence': len(high),
        'high_confidence_correct': sum(bool(r['correct']) for r in high),
        'high_confidence_wrong': sum(not r['correct'] for r in high),
    }


def _expected_for(
    run: dict[str, Any],
    fallback: tuple[str, int] | None,
    expected_path: Path | None = None,
) -> tuple[str | None, int | None]:
    expected = run.get("expected_diagnosis", run.get("expected"))
    location = "embedded expectation"
    if expected is None and expected_path and expected_path.exists():
        expected = _load_json(expected_path)
        location = f"expectation {expected_path}"
    if expected is None and fallback:
        expected = dict(zip(("root_cause_category", "failed_at_step"), fallback))
        location = "fixture expectation"
    if expected is None:
        return None, None
    if not isinstance(expected, dict):
        raise ValueError(f"{location} must be an object")
    category, step = expected.get("root_cause_category"), expected.get("failed_at_step")
    if not isinstance(category, str) or category not in {*FAILURE_CATEGORIES, "unknown"}:
        raise ValueError(f"{location}: invalid root_cause_category")
    indices = {s.get("original_index", i) for i, s in enumerate(run.get("spans", []), 1) if isinstance(s, dict)}
    if type(step) is not int or (step != 0 if category == "unknown" else step <= 0 or step not in indices):
        raise ValueError(f"{location}: failed_at_step must reference an original step (0 for unknown)")
    return category, step


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f'Evaluation expectation must be an object: {path}')
        return value
    except (json.JSONDecodeError, UnicodeError, OSError) as exc:
        raise ValueError(f"Cannot read evaluation expectation {path}: {exc}") from exc


def _rate(values: list[bool]) -> float:
    return sum(1 for value in values if value) / len(values) if values else 0.0


def _most_failed_category(failed_categories: dict[str, int]) -> str:
    if not failed_categories:
        return "none"
    return max(failed_categories.items(), key=lambda item: item[1])[0]
