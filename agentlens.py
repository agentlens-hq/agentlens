"""Public AgentLens SDK and CLI entrypoint."""

from __future__ import annotations

import argparse
import importlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agentlens_core.privacy import anonymize, residual
from agentlens_core.state import format_state_diff
from agentlens_core.storage import atomic_write, safe_path
from agentlens_sdk import (
    AgentLensClient,
    get_trace_context,
    init,
    load_run,
    load_runs,
    patch_langgraph,
    record_memory_snapshot,
    record_tool_result,
    run,
    save_run,
)
from agentlens_sdk.collector import RUNS_DIR, AmbiguousRunIdError, InvalidRunFilesError

__all__ = [
    "AgentLensClient",
    "get_trace_context",
    "init",
    "patch_langgraph",
    "record_memory_snapshot",
    "record_tool_result",
    "run",
    "save_run",
]

def _lazy(module: str, name: str):
    def call(*args, **kwargs):
        return getattr(importlib.import_module(module), name)(*args, **kwargs)
    return call

cluster_failures = _lazy("agentlens_engine.clustering", "cluster_failures")
print_clusters = _lazy("agentlens_engine.clustering", "print_clusters")
diagnose_run = _lazy("agentlens_engine.diagnose", "diagnose_run")
evaluate_cases = _lazy("agentlens_engine.evaluate", "evaluate_cases")
print_evaluation = _lazy("agentlens_engine.evaluate", "print_evaluation")
hallucination_summary = _lazy("agentlens_engine.hallucination", "hallucination_summary")
impact_summary = _lazy("agentlens_engine.impact", "impact_summary")
find_similar_failures = _lazy("agentlens_engine.similarity", "find_similar_failures")
run_status = _lazy("agentlens_engine.status", "run_status")
generate_html = _lazy("agentlens_engine.timeline", "generate_html")


def main() -> None:
    try:
        _dispatch()
    except (ValueError, OSError, UnicodeError, RecursionError) as exc:
        import sys
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentlens")
    subparsers = parser.add_subparsers(dest="command")

    runs_parser = subparsers.add_parser("runs")
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command")
    runs_subparsers.add_parser("list")
    show_parser = runs_subparsers.add_parser("show")
    show_parser.add_argument("run_id")
    view_parser = runs_subparsers.add_parser("view")
    view_parser.add_argument("run_id")
    prompt_parser = runs_subparsers.add_parser("prompt")
    prompt_parser.add_argument("run_id")
    prompt_parser.add_argument("--step", type=int, default=None, help="Show only this LLM call step (1-indexed)")
    replay_parser = runs_subparsers.add_parser("replay")
    replay_parser.add_argument("run_id")
    stitch_parser = runs_subparsers.add_parser("stitch")
    stitch_parser.add_argument("run_id")

    diagnose_parser = subparsers.add_parser("diagnose")
    diagnose_parser.add_argument("run_id")
    diagnose_parser.add_argument("--provider", choices=["openai", "anthropic"], help="Explicitly send a redacted compact trace to this provider; default is offline")
    similar_parser = subparsers.add_parser("similar")
    similar_parser.add_argument("run_id")
    similar_parser.add_argument("--top", type=int, default=5)
    subparsers.add_parser("clusters")
    anonymize_parser = subparsers.add_parser("anonymize")
    anonymize_parser.add_argument("run_id")
    upload_parser = subparsers.add_parser("upload")
    upload_subparsers = upload_parser.add_subparsers(dest="upload_command")
    upload_prepare_parser = upload_subparsers.add_parser(
        "prepare", help="Write anonymized-only run payloads for hosted sync."
    )
    upload_prepare_parser.add_argument(
        "run_id", nargs="?", help="Optional run id or prefix. Omit to prepare all local runs."
    )
    upload_prepare_parser.add_argument(
        "--out-dir",
        default=str(Path(".agentlens") / "upload"),
        help="Directory for anonymized payloads. Default: .agentlens/upload",
    )
    feedback_parser = subparsers.add_parser("feedback-template")
    feedback_parser.add_argument("run_id")
    stats_parser = subparsers.add_parser("stats")
    stats_parser.add_argument("run_id", nargs="?")
    subparsers.add_parser("evaluate")
    subparsers.add_parser("doctor")
    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument("--no-browser", action="store_true", help="Skip opening the timeline in a browser")
    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("--interval", type=float, default=0.5, help="Poll interval in seconds")

    return parser


def _dispatch() -> None:
    parser = _parser()
    args = parser.parse_args()

    if args.command == "demo":
        _run_demo(open_browser=not args.no_browser)
        return

    if args.command == "watch":
        _watch_runs(interval=args.interval)
        return

    if args.command == "runs" and args.runs_command == "list":
        _print_runs_list()
        return

    if args.command == "runs" and args.runs_command == "show":
        _print_run_detail(args.run_id)
        return

    if args.command == "runs" and args.runs_command == "view":
        _open_timeline(args.run_id)
        return

    if args.command == "runs" and args.runs_command == "prompt":
        _print_prompt_viewer(args.run_id, step=args.step)
        return

    if args.command == "runs" and args.runs_command == "replay":
        _replay_run(args.run_id)
        return

    if args.command == "runs" and args.runs_command == "stitch":
        _print_stitch(args.run_id)
        return

    if args.command == "diagnose":
        _print_diagnosis(args.run_id, provider=args.provider)
        return

    if args.command == "upload" and args.upload_command == "prepare":
        _prepare_anonymized_upload(run_id=args.run_id, out_dir=Path(args.out_dir))
        return

    if args.command == "similar":
        _print_similar(args.run_id, top_n=args.top)
        return

    if args.command == "clusters":
        _print_clusters()
        return

    if args.command == "anonymize":
        _anonymize_run(args.run_id)
        return

    if args.command == "feedback-template":
        _print_feedback_template(args.run_id)
        return

    if args.command == "stats":
        _print_stats(args.run_id)
        return

    if args.command == "evaluate":
        report = evaluate_cases()
        print_evaluation(report)
        if (report.get('fixture_cases', 0) != 6 or not report.get("scored_cases")
                or report.get("overall_accuracy", 0) < 1 or report.get("case_errors") or report.get("unscored_cases")):
            raise SystemExit(1)
        return

    if args.command == "doctor":
        _print_doctor()
        return

    parser.print_help()


def _print_runs_list() -> None:
    failure = None
    try:
        runs = load_runs()
    except InvalidRunFilesError as exc:
        runs, failure = exc.runs, exc
    if not runs:
        if failure:
            raise failure
        print("No AgentLens runs found in .agentlens/runs/")
        return

    print("AgentLens Runs")
    print()
    print(
        f"{'run_id':36}  {'name':24}  {'execution':10}  "
        f"{'diagnosis':18}  {'timestamp':25}  spans"
    )
    for item in runs[:20]:
        status = run_status(item)
        # When a failure is detected, show the root cause — it's the actionable
        # part. Otherwise show the status word (healthy / uncertain / unknown).
        diagnosis = status["root_cause"] or status["diagnosis_status"]
        print(
            f"{item.get('run_id', ''):36}  "
            f"{item.get('name', '')[:24]:24}  "
            f"{status['execution_status']:10}  "
            f"{diagnosis[:18]:18}  "
            f"{item.get('started_at', '')[:25]:25}  "
            f"{len(item.get('spans', []))}"
        )
    if failure:
        raise failure


def _print_run_detail(run_id: str) -> None:
    item = _load_run_or_report(run_id)
    if item is None:
        return

    print("AgentLens Run Detail")
    print()
    status = run_status(item)
    print(f"Run ID: {item.get('run_id')}")
    print(f"Name: {item.get('name')}")
    print(f"Execution status: {status['execution_status']}")
    diagnosis_line = status["diagnosis_status"]
    if status["root_cause"]:
        diagnosis_line += f" ({status['root_cause']}, confidence {status['confidence']:.2f})"
    print(f"Diagnosis status: {diagnosis_line}")
    print(f"Started: {item.get('started_at')}")
    print(f"Ended: {item.get('ended_at')}")
    spans = item.get("spans", [])
    if not isinstance(spans, list):
        spans = []
    print(f"Spans: {len(spans)}")
    print()

    for index, span in enumerate(spans, start=1):
        if not isinstance(span, dict):
            print(f"[{index}] malformed_span")
            print(_compact(span))
            print()
            continue

        span_type = span.get("type")
        print(f"[{span.get('original_index', index)}] {span_type}")
        if span_type == "llm_call":
            print(f"Provider: {span.get('provider')}")
            print(f"Model: {span.get('model')}")
            print(f"Latency: {span.get('latency_ms')} ms")
            print(f"Stop reason: {span.get('stop_reason')}")
            print(f"Usage: {_compact(span.get('usage'))}")
            print(f"Input messages: {_compact(span.get('input_messages'))}")
            print(f"Response: {_compact(span.get('response_content'))}")
        elif span_type == "tool_call":
            print(f"Tool: {span.get('tool_name')}")
            print(f"Input: {_compact(span.get('input'))}")
            print(f"Output: {_compact(span.get('output'))}")
        elif span_type == "error":
            print(f"Error: {span.get('error')}")
            print(f"Context: {_compact(span.get('context'))}")
        else:
            print(_compact(span))
        print()


def _compact(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=True, default=str)
    return text if len(text) <= 500 else text[:497] + "..."


def _print_diagnosis(run_id: str, provider: str | None = None) -> None:
    item = _load_run_or_report(run_id)
    if item is None:
        return

    try:
        diagnosis = diagnose_run(item, provider=provider)
    except ValueError as exc:
        raise ValueError(f"Diagnosis failed: {exc}") from exc
    if diagnosis.get("confidence", 0) < 0.6:
        print("AgentLens Diagnosis")
        print("===================")
        print()
        print("SOURCE:")
        print(f"  {_diagnosis_source_label(diagnosis)}")
        print()
        print("LOW CONFIDENCE")
        print()
        print(diagnosis.get("low_confidence_message"))
        print("We are not treating this as a final root cause yet.")
        print()
        print(f"EVIDENCE STRENGTH: {diagnosis.get('evidence_strength', 'insufficient')}")
        print("POSSIBLE CAUSES (only if supported):")
        for cause in diagnosis.get("likely_causes", [])[:2]:
            print(f"- {cause}")
        print()
        print("SUGGESTED FIXES:")
        for fix in diagnosis.get("likely_fixes", [])[:2]:
            print(f"- {fix}")
        return

    print("AgentLens Diagnosis")
    print("===================")
    print()
    print("SOURCE:")
    print(f"  {_diagnosis_source_label(diagnosis)}")
    print()
    print("ROOT CAUSE:")
    print(f"  {diagnosis['root_cause_category']}")
    print()
    print("FAILED AT (ROOT-CAUSE STEP):")
    tool = diagnosis.get("failed_at_tool") or "unknown tool"
    print(f"  Step {diagnosis['failed_at_step']} ({tool})")
    print()
    print("WHY:")
    print(f"  {diagnosis['explanation']}")
    print()
    print("SUGGESTED FIX (not verified):")
    print(f"  {diagnosis['fix']}")
    print()
    print("SECONDARY:")
    secondary = diagnosis.get("secondary_issues") or []
    if secondary:
        for issue in secondary:
            print(f"- {issue}")
    else:
        print("  None")
    print()
    print(f"EVIDENCE STRENGTH: {diagnosis.get('evidence_strength', 'unknown')}")
    print(f"Confidence score (not a calibrated probability): {diagnosis['confidence']:.2f}")

    impact = diagnosis.get("impact")
    if impact:
        print()
        print("IMPACT:")
        print(f"  {impact_summary(impact)}")
        print(
            f"  Run total: {impact['total_tokens']} tokens / "
            f"${impact['total_cost_usd']:.6f}"
        )

    hallucinations = diagnosis.get("hallucinations") or []
    if hallucinations:
        print()
        print("SCHEMA / EXPLICIT CONTRADICTION FINDINGS:")
        for h in hallucinations:
            sev = h.get("severity", "?").upper()
            print(f"  [{sev}] {h.get('detail', '')}")


def _anonymize_run(run_id: str) -> None:
    item = _load_run_or_report(run_id)
    if item is None:
        return

    anonymized = _anonymize_value(item)
    output_path = safe_path(Path.cwd(), item.get('run_id', run_id), '.anonymized.json')
    atomic_write(output_path, anonymized)
    print(f"Wrote anonymized trace to {output_path}")
    print("Review it before sharing. AgentLens removes obvious secrets, but you know your data best.")


# Patterns scanned on the ALREADY-anonymized payload as a last line of defense
# before it leaves the machine. If any of these survive anonymization, the run is
# refused rather than uploaded — a leak here is the one that actually matters.
_RESIDUAL_PII_PATTERNS = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d[ -]?){15,16}\b",
    "phone": r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b",
}


def _residual_pii(anonymized: dict[str, Any]) -> list[str]:
    """Return the kinds of PII still present in an anonymized payload (should be none)."""
    return residual(anonymized)


def _write_anonymized_run(item: dict[str, Any], out_dir: Path) -> Path | None:
    """Anonymize a run and write it for upload — but refuse if PII survived."""
    anonymized = _anonymize_value(item)
    run_id = item.get("run_id", "")
    output_path = safe_path(out_dir, run_id, '.anonymized.json')
    leaks = _residual_pii(anonymized)
    if leaks:
        print(f"SKIPPED run '{run_id}': anonymized payload still contains {', '.join(leaks)} — not written.")
        return None
    atomic_write(output_path, anonymized)
    return output_path


def _prepare_anonymized_upload(run_id: str | None, out_dir: Path) -> None:
    """Prepare anonymized-only payloads for hosted upload/sync.

    Writes only ``*.anonymized.json`` files plus a manifest. The hosted sync layer
    should consume this directory, never raw ``.agentlens/runs``. Each run is
    re-scanned for residual PII after anonymization and skipped if any survives.
    """
    if run_id:
        item = _load_run_or_report(run_id)
        if item is None:
            return
        runs = [item]
    else:
        runs = load_runs()

    if not runs:
        print("No AgentLens runs found in .agentlens/runs/")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    written = [path for item in runs if (path := _write_anonymized_run(item, out_dir))]
    manifest_path = out_dir / "manifest.json"
    atomic_write(
        manifest_path,
            {
                "payload_type": "agentlens_anonymized_runs",
                "raw_upload_allowed": False,
                "run_count": len(written),
                "skipped_count": len(runs) - len(written),
                "files": [path.name for path in written],
            },
        )

    print(f"Prepared {len(written)} anonymized run(s) in {out_dir}")
    if len(written) != len(runs):
        print(f"Skipped {len(runs) - len(written)} run(s) that still contained PII after anonymization.")
    print(f"Wrote upload manifest to {manifest_path}")
    print("Raw .agentlens/runs/*.json files were not copied.")
    if len(written) != len(runs):
        raise SystemExit(1)


def _print_feedback_template(run_id: str) -> None:
    item = _load_run_or_report(run_id)
    if item is None:
        return
    run_id = item.get("run_id", run_id)
    print(f"# AgentLens Feedback: {run_id}")
    print()
    print("## Independent ground truth (complete BEFORE diagnose, runs show, or runs view)")
    print()
    print("- Source: regression / internal_natural / external_developer")
    print("- Recorded at:")
    print("- Observed behavior:")
    print("- Expected category / original step (unknown is allowed):")
    print("- Expected explanation / fix:")
    print("- Had you already seen AgentLens's answer? Yes / No:")
    print()
    print("## AgentLens result (complete AFTER ground truth is recorded)")
    print()
    print("- Category / original step:")
    print("- Source / confidence score:")
    print("- Category correct / step correct:")
    print("- Confidence believable / confident-wrong:")
    print()
    print("## What broke?")
    print()
    print("- ")
    print()
    print("## Was diagnosis correct?")
    print()
    print("- Yes / No / Partially:")
    print("- Why:")
    print()
    print("## Was diagnosis useful?")
    print()
    print("- Yes / No / Partially:")
    print("- Did it save debugging time:")
    print()
    print("## Did the suggested fix work?")
    print()
    print("- Yes / No / Not tried:")
    print("- Fix helpful / issue resolved (separate answers):")
    print("- Notes:")
    print()
    print("## What was confusing?")
    print()
    print("- Install:")
    print("- Setup:")
    print("- CLI output:")
    print("- Diagnosis wording:")
    print()
    print("## Would you use this again?")
    print()
    print("- Yes / No / Maybe:")
    print("- Why:")
    print()
    print("## Would you pay for this?")
    print()
    print("- Yes / No / Maybe:")
    print("- What would need to improve:")


def _print_stats(run_id: str | None) -> None:
    if run_id:
        item = _load_run_or_report(run_id)
        if item is None:
            return
        _print_run_stats(item)
        return

    runs = load_runs()
    if not runs:
        print("No AgentLens runs found in .agentlens/runs/")
        return

    summaries = [_summarize_run(item) for item in runs]
    totals = _merge_stats(summaries)

    print("AgentLens Stats")
    print()
    print(f"Runs analyzed: {len(summaries)}")
    print(f"LLM calls: {totals['llm_calls']}")
    print(f"Tool calls: {totals['tool_calls']}")
    print(f"Errors: {totals['errors']}")
    print(f"Input tokens: {totals['input_tokens']}")
    print(f"Output tokens: {totals['output_tokens']}")
    print(f"Total tokens: {totals['total_tokens']}")
    print(f"Captured latency: {_format_ms(totals['latency_ms'])}")
    print(f"Known cost subtotal: {_format_cost(totals['cost_usd'])}")
    print(f"Calls with unknown pricing: {sum(s['unknown_cost_calls'] for s in summaries)}")
    print()
    print(f"{'run_id':36}  {'name':24}  {'status':8}  {'llm':>3}  {'tool':>4}  {'tokens':>8}  latency")
    for summary in summaries:
        print(
            f"{summary['run_id'][:36]:36}  "
            f"{summary['name'][:24]:24}  "
            f"{summary['status'][:8]:8}  "
            f"{summary['llm_calls']:>3}  "
            f"{summary['tool_calls']:>4}  "
            f"{summary['total_tokens']:>8}  "
            f"{_format_ms(summary['latency_ms'])}"
        )


def _print_run_stats(item: dict[str, Any]) -> None:
    summary = _summarize_run(item)

    print("AgentLens Run Stats")
    print()
    print(f"Run ID: {summary['run_id']}")
    print(f"Name: {summary['name']}")
    print(f"Status: {summary['status']}")
    print(f"Started: {item.get('started_at')}")
    print(f"Ended: {item.get('ended_at')}")
    print(f"Duration: {_format_ms(summary['duration_ms'])}")
    print()
    print("Calls:")
    print(f"  LLM calls: {summary['llm_calls']}")
    print(f"  Tool calls: {summary['tool_calls']}")
    print(f"  Errors: {summary['errors']}")
    print()
    print("Tokens:")
    print(f"  Input tokens: {summary['input_tokens']}")
    print(f"  Output tokens: {summary['output_tokens']}")
    print(f"  Total tokens: {summary['total_tokens']}")
    print()
    print("Performance:")
    print(f"  Captured latency: {_format_ms(summary['latency_ms'])}")
    if summary["slowest_step"]:
        print(f"  Slowest step: {summary['slowest_step']}")
    else:
        print("  Slowest step: unavailable")
    print()
    print("Cost:")
    print(f"  Known cost subtotal: {_format_cost(summary['cost_usd'])}")
    print(f"  Calls with unknown pricing: {summary['unknown_cost_calls']}")
    if summary["cost_usd"] == 0:
        print("  Note: provider billing cost is not captured unless traces include cost_usd.")
    print()
    print("Providers:")
    _print_count_map(summary["providers"])
    print()
    print("Models:")
    _print_count_map(summary["models"])


def _print_similar(run_id: str, top_n: int = 5) -> None:
    """Find historically similar failures and print them."""
    item = _load_run_or_report(run_id)
    if item is None:
        return

    try:
        diagnosis = diagnose_run(item, use_llm=False)
    except ValueError as exc:
        print(f"Could not diagnose run: {exc}")
        return

    all_runs = load_runs()
    similar = find_similar_failures(diagnosis, item, all_runs, top_n=top_n)

    print(f"Similar Failures — {item.get('name', run_id)}")
    print(f"Root cause: {diagnosis.get('root_cause_category')}  ·  failed tool: {diagnosis.get('failed_at_tool') or 'n/a'}")
    print("=" * 60)
    print()

    if not similar:
        print("No similar historical failures found.")
        print("Run more agents to build up a failure library.")
        return

    for i, match in enumerate(similar, start=1):
        pct = int(match["similarity"] * 100)
        print(f"#{i}  {match['name'] or match['run_id'][:8]}  —  {pct}% similar")
        print(f"     Match: {match['match_reason']}")
        print(f"     Category: {match['category']}  ·  Tool: {match['failed_at_tool'] or 'n/a'}")
        started = (match.get("started_at") or "")[:19].replace("T", " ")
        if started:
            print(f"     When: {started} UTC")
        if match.get("fix"):
            print(f"     Suggested fix (unverified): {match['fix'][:120]}{'…' if len(match['fix']) > 120 else ''}")
        outcome = match.get('developer_fix_outcome')
        if outcome:
            print(f"     Developer-reported outcome: {outcome['status']} ({outcome['recorded_at']})")
            print(f"     Change actually tried: {outcome['fix']}")
        print()


def _print_clusters() -> None:
    """Show failure clusters across all runs."""
    all_runs = load_runs()
    clusters = cluster_failures(all_runs)
    print_clusters(clusters, total_runs=len(all_runs))
    if clusters:
        top = clusters[0]
        pct = int(top["percentage"] * 100)
        print(f"Top fix opportunity: fix '{top['category']}' on '{top['failed_tool'] or 'any tool'}' "
              f"to eliminate {pct}% of failures.")


def _open_timeline(run_id: str) -> None:
    """Generate a self-contained HTML timeline and open it in the default browser."""
    import tempfile
    import webbrowser

    item = _load_run_or_report(run_id)
    if item is None:
        return
    html = generate_html(item, diagnosis=_load_diagnosis_for(item))
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(html)
        tmp_path = tmp.name
    opened = webbrowser.open(Path(tmp_path).as_uri())
    message = "Timeline opened in browser" if opened else "Browser could not open; timeline generated"
    print(f"{message}: {tmp_path}")


def _load_diagnosis_for(item: dict[str, Any]) -> dict[str, Any] | None:
    """Find a diagnosis for this run: saved file first, else offline diagnosis for failed runs."""
    return diagnose_run(item, use_llm=False)


def _print_prompt_viewer(run_id: str, step: int | None = None) -> None:
    """Print captured prompt data, not a reconstruction of the provider wire request."""
    item = _load_run_or_report(run_id)
    if item is None:
        return

    spans = [s for s in (item.get("spans") or []) if isinstance(s, dict) and s.get("type") == "llm_call"]
    if not spans:
        print("No LLM calls found in this run.")
        return

    if step is not None:
        spans = [span for span in spans if span.get("original_index") == step]
        if not spans:
            raise ValueError(f"No LLM span at original step {step}.")

    print(f"AgentLens LLM Prompt Viewer — {item.get('name', run_id)}")
    print("=" * 60)

    for offset, span in enumerate(spans):
        step_num = span.get("original_index", offset + 1)
        model = span.get("model") or "unknown"
        provider = span.get("provider") or ""
        print(f"\nStep {step_num}: {provider}/{model}")
        print("─" * 60)

        for field in ("system", "instructions"):
            if field in span:
                print(f"[{field.upper()}]")
                print(_prompt_content(span[field]))

        messages = span.get("input_messages") or []
        if messages:
            for msg in messages:
                if not isinstance(msg, dict):
                    print(_prompt_content(msg))
                    continue
                role = str(msg.get("role") or msg.get("type") or "unknown").upper()
                print(f"[{role}]")
                # Preserve call IDs, tool outputs and provider-specific message fields.
                body = msg["content"] if set(msg) <= {"role", "content"} and "content" in msg else msg
                print(_prompt_content(body))
                print()
        else:
            print("(no messages captured)")

        tools = span.get("tools") or []
        if tools:
            print(f"Tools available ({len(tools)}):")
            for t in tools:
                print(_prompt_content(t))
            print()

        resp = span.get("response_content")
        if resp is not None:
            print("Response:")
            if isinstance(resp, list):
                for block in resp:
                    if isinstance(block, dict):
                        btype = block.get("type")
                        if btype == "text":
                            print(f"  [text] {block.get('text', '')}")
                        elif btype == "tool_use":
                            print(f"  [tool_use] {block.get('name')}({json.dumps(block.get('input', {}), default=str)})")
                        else:
                            print(f"  {json.dumps(block, default=str)}")
                    else:
                        print(f"  {block}")
            else:
                print(f"  {_compact(resp)}")
            stop = span.get("stop_reason")
            if stop:
                print(f"  Stop reason: {stop}")

        usage = span.get("usage")
        cost = span.get("cost_usd") or 0
        if isinstance(usage, dict):
            inp, out, _ = _usage_counts(usage)
            cost_str = f"  Cost: ${cost:.6f}" if cost > 0 else ""
            print(f"\n  Tokens: {inp} in / {out} out{cost_str}")


def _prompt_content(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, indent=2, default=str)


def _usage_counts(usage: Any) -> tuple[int, int, int]:
    """Provider aliases are alternatives, not additive counters; explicit zero is valid."""
    if not isinstance(usage, dict):
        return 0, 0, 0
    inp = int(_number(usage.get("input_tokens", usage.get("prompt_tokens"))))
    out = int(_number(usage.get("output_tokens", usage.get("completion_tokens"))))
    total = inp + out if usage.get("total_tokens") is None else int(_number(usage["total_tokens"]))
    return inp, out, total


def _replay_run(run_id: str) -> None:
    """Inspect recorded spans; never execute an agent or provider request."""
    item = _load_run_or_report(run_id)
    if item is None:
        return

    spans = [s for s in (item.get("spans") or []) if isinstance(s, dict)]
    if not spans:
        print("No spans in this run.")
        return

    print(f"AgentLens Session Replay — {item.get('name', run_id)}")
    print("=" * 60)
    print(f"  {len(spans)} span(s)  ·  status: {item.get('status', '?')}")
    print()
    print("ENTER: next / finish; b: back; f: full current span; d: state diff; q: quit.")

    cursor = -1
    while True:
        try:
            command = input("\n[Replay command] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nReplay stopped.")
            return
        if command == 'q':
            return
        if command in ('f', 'd'):
            if cursor < 0:
                print('Advance to a span first.')
            elif command == 'f':
                print(json.dumps(spans[cursor], indent=2, ensure_ascii=True))
            else:
                snapshots = [s for s in spans[:cursor + 1] if s.get('type') == 'memory_snapshot' and 'state' in s]
                if len(snapshots) < 2:
                    print('Two recorded state snapshots are required for comparison.')
                else:
                    print(format_state_diff(snapshots[-2]['state'], snapshots[-1]['state']))
            continue
        if command == 'b':
            cursor = max(0, cursor - 1)
        elif command in ('', 'n'):
            cursor += 1
            if cursor == len(spans):
                break
        else:
            print('Use ENTER, b, f, d, or q.')
            continue
        i, span = cursor + 1, spans[cursor]
        original_step = span.get('original_index', i)

        stype = span.get("type", "unknown")
        print(f"\n{'━' * 60}")
        print(f"Step {original_step} (span {i}/{len(spans)})  ·  {stype.upper()}")
        print('━' * 60)

        if stype == "llm_call":
            print(f"Provider : {span.get('provider', '?')}")
            print(f"Model    : {span.get('model', '?')}")
            lat = span.get("latency_ms")
            if lat:
                print(f"Latency  : {_format_ms(lat)}")
            cost = span.get("cost_usd") or 0
            if cost > 0:
                print(f"Cost     : ${cost:.6f}")

            messages = span.get("input_messages") or []
            if messages:
                print(f"\nWhat the agent knows ({len(messages)} message(s)):")
                for msg in messages[-3:]:  # Show last 3 to keep it concise
                    if not isinstance(msg, dict):
                        continue
                    role = str(msg.get("role") or "?").upper()
                    content = msg.get("content", "")
                    body = content if isinstance(content, str) else json.dumps(content, default=str)
                    print(f"  [{role}] {body[:200]}{'…' if len(body) > 200 else ''}")

            tools = span.get("tools") or []
            if tools:
                names = [
                    t.get("name") or (t.get("function") or {}).get("name") or "?"
                    for t in tools if isinstance(t, dict)
                ]
                print(f"\nTools available: {', '.join(names)}")

            resp = span.get("response_content")
            if resp:
                stop = span.get("stop_reason", "")
                print(f"\n  ↳ Stop reason: {stop}")
                if isinstance(resp, list):
                    for block in resp:
                        if isinstance(block, dict):
                            if block.get("type") == "tool_use":
                                print(f"  ↳ Called tool: {block.get('name')}({json.dumps(block.get('input', {}), default=str)[:100]})")
                            elif block.get("type") == "text":
                                text = _prompt_content(block.get("text"))
                                print(f"  ↳ Response text: {text[:150]}{'…' if len(text)>150 else ''}")

        elif stype == "tool_call":
            print(f"Tool   : {span.get('tool_name', '?')}")
            inp = span.get("input")
            out = span.get("output")
            if inp is not None:
                print(f"Input  : {_compact(inp)}")
            if out is not None:
                is_err = isinstance(out, dict) and (out.get("status") == "error" or out.get("error"))
                prefix = "⚠ Output (ERROR)" if is_err else "Output"
                print(f"{prefix}: {_compact(out)}")

        elif stype == "error":
            print(f"⚠ Error: {span.get('error', 'unknown')}")
            ctx = span.get("context")
            if ctx:
                print(f"  Context: {_compact(ctx)}")

        elif stype == "memory_snapshot":
            label = span.get("label", "")
            print(f"Label : {label}")
            state = span.get("state")
            if state:
                print(f"State : {_compact(state)}")

        else:
            print(_compact(span))

    print(f"\n{'═' * 60}")
    print(f"End of replay  ·  status: {item.get('status', '?')}")
    llm_n = sum(1 for s in spans if s.get("type") == "llm_call")
    tool_n = sum(1 for s in spans if s.get("type") == "tool_call")
    err_n = sum(1 for s in spans if s.get("type") == "error")
    print(f"Summary: {llm_n} LLM call(s), {tool_n} tool call(s), {err_n} error(s)")


def _print_stitch(run_id: str) -> None:
    """Show a multi-agent trace tree rooted at this run."""
    root = _load_run_or_report(run_id)
    if root is None:
        return

    all_runs = load_runs()

    def children_of(rid: str) -> list[dict[str, Any]]:
        return [r for r in all_runs if r.get("parent_run_id") == rid]

    visited = {root.get("run_id")}

    def print_tree(r: dict[str, Any], prefix: str = "", is_last: bool = True) -> None:
        rid = r.get("run_id")
        if rid in visited:
            print(f"{prefix}Cycle detected at run {rid}; stopping this branch.")
            return
        visited.add(rid)
        connector = "└── " if is_last else "├── "
        spans = r.get("spans") or []
        status = r.get("status", "?")
        status_icon = {"success": "✓", "error": "✗", "running": "○"}.get(status, "?")
        name = r.get("name", "?")[:30]
        rid_short = (r.get("run_id") or "")[:8]
        n_spans = len([s for s in spans if isinstance(s, dict)])
        print(f"{prefix}{connector}{rid_short}  {name:30}  [{n_spans} spans]  {status_icon} {status}")
        kids = children_of(r.get("run_id", ""))
        child_prefix = prefix + ("    " if is_last else "│   ")
        for j, child in enumerate(kids):
            print_tree(child, child_prefix, is_last=(j == len(kids) - 1))

    print(f"AgentLens Multi-Agent Trace Tree — {root.get('name', run_id)}")
    print("=" * 60)
    print()
    # Print root without connector
    spans = root.get("spans") or []
    n_spans = len([s for s in spans if isinstance(s, dict)])
    status = root.get("status", "?")
    status_icon = {"success": "✓", "error": "✗", "running": "○"}.get(status, "?")
    print(f"{(root.get('run_id') or '')[:8]}  {root.get('name','?')[:30]:30}  [{n_spans} spans]  {status_icon} {status}  (root)")
    kids = children_of(root.get("run_id", ""))
    if not kids:
        print("\n  No child runs found. Child runs must be started with parent_context set.")
        print("  Example: agentlens.init(parent_context=agentlens.get_trace_context())")
        return
    for j, child in enumerate(kids):
        print_tree(child, "", is_last=(j == len(kids) - 1))
    print()


def _run_demo(open_browser: bool = True) -> None:
    """One-command demo: capture a broken agent run, diagnose it, open the timeline.

    Works offline, requires no API key — the agent is simulated through the real
    capture pipeline so the saved run is identical in shape to a live capture.
    """
    from agentlens_sdk.collector import (
        _current_run,
        _finalize_run,
        append_span,
        start_run,
    )

    print("AgentLens Demo")
    print("=" * 60)
    print()
    print("Simulating a broken customer-support agent...")
    print("  Two tools with near-identical descriptions: search_web, query_db")
    print("  The task needs local records. Watch what the agent picks.")
    print()

    run_data = start_run(name="demo_customer_support_agent")
    token = _current_run.set(run_data)
    try:
        tools = [
            {
                "name": "search_web",
                "description": "find info about a topic",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "query_db",
                "description": "find info about a topic",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        ]
        append_span(
            {
                "type": "llm_call",
                "provider": "anthropic",
                "ts": datetime.now().astimezone().isoformat(),
                "latency_ms": 412.6,
                "model": "claude-3-5-sonnet-latest",
                "input_messages": [
                    {
                        "role": "user",
                        "content": "Find the renewal status for customer:alex using local records.",
                    }
                ],
                "tools": tools,
                "response_content": [
                    {
                        "type": "text",
                        "text": "Both tools say they find info about a topic. I will use search_web.",
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_demo_001",
                        "name": "search_web",
                        "input": {"query": "customer:alex renewal status"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 158, "output_tokens": 42},
                "cost_usd": 0.001104,
            }
        )
        record_tool_result(
            tool_name="search_web",
            input={"query": "customer:alex renewal status"},
            output={
                "status": "error",
                "error": "Network access disabled. Customer records are only available in query_db.",
            },
            tool_use_id="toolu_demo_001",
        )
        run_data["status"] = "error"
        run_data["error"] = "agent picked the wrong tool"
    finally:
        _finalize_run(run_data)
        _current_run.reset(token)

    run_id = run_data["run_id"]
    print(f"Run captured: {run_id[:8]}  ({len(run_data['spans'])} spans)")
    print()
    print("Diagnosing...")
    print()
    _print_diagnosis(run_id)
    print()
    print("=" * 60)
    print("Next steps:")
    print(f"  agentlens runs view {run_id[:8]}     # visual timeline")
    print(f"  agentlens runs prompt {run_id[:8]}   # captured prompt data")
    print()
    print("Enable capture, then use @agentlens.run(name=...) to group and save:")
    print("  import agentlens")
    print("  agentlens.init()   # before creating your Anthropic/OpenAI client")
    if open_browser:
        print()
        print("Opening the timeline viewer...")
        _open_timeline(run_id)


def _watch_runs(interval: float = 0.5) -> None:
    """Display changed saved snapshots; SDK completion/save_run controls persistence."""
    import math
    import time

    from agentlens_core.watch import SnapshotWatcher

    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("Watch interval must be finite and greater than zero.")
    watcher = SnapshotWatcher(RUNS_DIR)
    watcher.poll()  # Establish the baseline without replaying historical runs.
    print(f"Watching saved snapshots in {RUNS_DIR} (not live provider events).")
    try:
        while True:
            for path, snapshot in watcher.poll():
                if isinstance(snapshot, str):
                    print(f"WARN {snapshot}")
                    continue
                print(f"Run {snapshot.get('run_id', path.stem)}: {snapshot.get('status', 'unknown')}")
                for span in snapshot['spans']:
                    print(f"  [{span['original_index']}] {span.get('type', '?')} "
                          f"{span.get('tool_name') or span.get('model') or ''}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped watching.")


def _load_run_or_report(run_id: str) -> dict[str, Any] | None:
    try:
        item = load_run(run_id)
    except AmbiguousRunIdError as exc:
        print(f"Multiple runs match '{exc.prefix}'. Please use a longer run_id.")
        for match in exc.matches[:10]:
            print(f"- {match}")
        if len(exc.matches) > 10:
            print(f"...and {len(exc.matches) - 10} more")
        raise SystemExit(1) from None

    if item is None:
        raise ValueError(f"Run not found: {run_id}. Run agentlens runs list.")
    return item


def _diagnosis_source_label(diagnosis: dict[str, Any]) -> str:
    if diagnosis.get("diagnosis_source") == "llm":
        return "LLM diagnosis"
    return "Heuristic fallback"


def _summarize_run(item: dict[str, Any]) -> dict[str, Any]:
    spans = item.get("spans", [])
    if not isinstance(spans, list):
        spans = []
    safe_spans = [span for span in spans if isinstance(span, dict)]

    providers: dict[str, int] = {}
    models: dict[str, int] = {}
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    latency_ms = 0.0
    cost_usd = 0.0
    slowest_latency = -1.0
    slowest_step = ""

    for index, span in enumerate(safe_spans, start=1):
        provider = span.get("provider")
        model = span.get("model")
        if provider:
            providers[str(provider)] = providers.get(str(provider), 0) + 1
        if model:
            models[str(model)] = models.get(str(model), 0) + 1

        usage = span.get("usage") if span.get("type") == "llm_call" else None
        usage_input, usage_output, usage_total = _usage_counts(usage)
        input_tokens += int(usage_input)
        output_tokens += int(usage_output)
        total_tokens += int(usage_total)

        span_latency = _number(span.get("latency_ms"))
        latency_ms += span_latency
        if span_latency > 0 and span_latency > slowest_latency:
            slowest_latency = span_latency
            slowest_step = _describe_span(span.get("original_index", index), span, span_latency)

        cost_usd += _extract_cost_usd(span)

    return {
        "run_id": str(item.get("run_id") or ""),
        "name": str(item.get("name") or ""),
        "status": str(item.get("status") or ""),
        "llm_calls": sum(1 for span in safe_spans if span.get("type") == "llm_call"),
        "tool_calls": _count_tool_invocations(safe_spans),
        "errors": sum(1 for span in safe_spans if span.get("type") == "error"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "duration_ms": _duration_ms(item.get("started_at"), item.get("ended_at")),
        "cost_usd": cost_usd,
        "unknown_cost_calls": sum(s.get("type") == "llm_call" and s.get("cost_usd") is None for s in safe_spans),
        "slowest_step": slowest_step if slowest_latency >= 0 else "",
        "providers": providers,
        "models": models,
    }


def _merge_stats(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "llm_calls": 0,
        "tool_calls": 0,
        "errors": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "latency_ms": 0.0,
        "cost_usd": 0.0,
    }
    for summary in summaries:
        for key in totals:
            totals[key] += summary[key]
    return totals


def _count_tool_invocations(spans: list[dict[str, Any]]) -> int:
    invocations: set[str] = set()
    for index, span in enumerate(spans):
        if span.get("type") != "tool_call":
            continue
        tool_use_id = span.get("tool_use_id")
        if tool_use_id:
            key = f"id:{tool_use_id}"
        else:
            key = json.dumps(
                {"tool_name": span.get("tool_name"), "input": span.get("input")},
                sort_keys=True,
                default=str,
            )
            if key == '{"input": null, "tool_name": null}':
                key = f"span:{index}"
        invocations.add(key)
    return len(invocations)


def _extract_cost_usd(value: Any) -> float:
    if not isinstance(value, dict) or value.get("type") != "llm_call":
        return 0.0
    return _number(value.get("cost_usd"))


def _duration_ms(started_at: Any, ended_at: Any) -> float:
    if not isinstance(started_at, str) or not isinstance(ended_at, str):
        return 0.0
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        ended = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    try:
        return max((ended - started).total_seconds() * 1000, 0.0)
    except TypeError:
        return 0.0


def _describe_span(index: int, span: dict[str, Any], latency_ms: float) -> str:
    label = str(span.get("type") or "unknown")
    if span.get("tool_name"):
        label += f" ({span['tool_name']})"
    elif span.get("model"):
        label += f" ({span['model']})"
    return f"Step {index}: {label} at {_format_ms(latency_ms)}"


def _print_count_map(values: dict[str, int]) -> None:
    if not values:
        print("  None captured")
        return
    for name, count in sorted(values.items()):
        print(f"  {name}: {count}")


def _format_ms(value: float) -> str:
    if value <= 0:
        return "unavailable"
    if value < 1000:
        return f"{value:.2f} ms"
    return f"{value / 1000:.2f} s"


def _format_cost(value: float) -> str:
    if value <= 0:
        return "not captured"
    return f"${value:.6f}"


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _print_doctor() -> None:
    checks = [
        _doctor_check("imports", _doctor_imports),
        _doctor_check("local storage", _doctor_local_storage),
        _doctor_check("diagnosis fixture", _doctor_diagnosis_fixture),
        _doctor_check("messy trace handling", _doctor_messy_trace_handling),
        _doctor_check("anonymization", _doctor_anonymization),
        _doctor_check("evaluation", _doctor_evaluation),
    ]

    print("AgentLens Doctor")
    print()
    for check in checks:
        line = f"{check['status']:<5} {check['name']}"
        if check["message"]:
            line += f" - {check['message']}"
        print(line)
    print()

    if any(check["status"] == "FAIL" for check in checks):
        print("Result: needs attention")
        raise SystemExit(1)
    elif any(check["status"] == "WARN" for check in checks):
        print("Result: healthy with warnings")
    else:
        print("Result: healthy")


def _doctor_check(name: str, check: Any) -> dict[str, str]:
    try:
        status, message = check()
    except Exception as exc:  # Doctor should report broken states, not crash.
        status, message = "FAIL", str(exc)
    return {"name": name, "status": status, "message": message}


def _doctor_imports() -> tuple[str, str]:
    modules = [
        "agentlens_sdk",
        "agentlens_sdk.collector",
        "agentlens_engine.classifier",
        "agentlens_engine.preprocess",
        "agentlens_engine.diagnose",
        "agentlens_engine.evaluate",
        "agentlens_engine.fixes",
    ]
    for module in modules:
        importlib.import_module(module)

    # Verify the public SDK surface is intact (not a self-referential import)
    import agentlens as _al
    if not callable(getattr(_al, "init", None)):
        return "FAIL", "agentlens.init is missing or not callable"

    commands = next(action.choices for action in _parser()._actions if isinstance(action, argparse._SubParsersAction))
    if not set(commands).issuperset({"doctor", "diagnose", "evaluate"}):
        return "FAIL", "required CLI commands are missing"
    return "PASS", ""


def _doctor_local_storage() -> tuple[str, str]:
    import uuid
    run_id = "doctor_" + uuid.uuid4().hex
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{run_id}.json"
    payload = {
        "run_id": run_id,
        "name": "doctor",
        "started_at": "2026-05-18T00:00:00+00:00",
        "ended_at": "2026-05-18T00:00:01+00:00",
        "status": "success",
        "spans": [],
    }
    try:
        atomic_write(path, payload)
        loaded = load_run(run_id)
        if not loaded or loaded.get("run_id") != run_id:
            return "FAIL", "run JSON could not be read back"
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return "PASS", ""


def _doctor_diagnosis_fixture() -> tuple[str, str]:
    diagnosis = diagnose_run(_doctor_tool_selection_run(), use_llm=False)
    required = {
        "root_cause_category",
        "failed_at_step",
        "confidence",
        "explanation",
        "fix",
    }
    missing = required - set(diagnosis)
    if missing:
        return "FAIL", f"diagnosis missing {', '.join(sorted(missing))}"
    if not diagnosis["root_cause_category"]:
        return "FAIL", "diagnosis did not return a category"
    if not isinstance(diagnosis["failed_at_step"], int):
        return "FAIL", "diagnosis did not return a failed step"
    if not isinstance(diagnosis["confidence"], (int, float)):
        return "FAIL", "diagnosis did not return confidence"
    if not diagnosis["explanation"] or not diagnosis["fix"]:
        return "FAIL", "diagnosis output was not readable"
    return "PASS", ""


def _doctor_messy_trace_handling() -> tuple[str, str]:
    messy_run = {
        "run_id": "agentlens_doctor_messy",
        "name": "doctor_messy",
        "status": "running",
        "spans": [
            "malformed span",
            {
                "id": "partial",
                "type": "llm_call",
                "provider": "openai",
                "input_messages": [],
                "response_content": {"unexpected": ["partial", None]},
            },
        ],
    }
    diagnosis = diagnose_run(messy_run, use_llm=False)
    if diagnosis.get("confidence", 1.0) >= 0.6:
        return "WARN", "messy trace produced medium/high confidence"
    if not diagnosis.get("low_confidence_message"):
        return "FAIL", "messy trace did not include low-confidence messaging"
    return "PASS", ""


def _doctor_anonymization() -> tuple[str, str]:
    raw = {
        "email": "alex@example.com",
        "api_key": "sk-test123456789abcdef",
        "headers": {"Authorization": "Bearer testBearerToken123456789"},
        "text": "password=hunter2 secret=supersecretvalue token=tok_live_1234567890abcdef",
        "usage": {"input_tokens": 123, "output_tokens": 45, "total_tokens": 168},
    }
    cleaned = _anonymize_value(raw)
    cleaned_text = json.dumps(cleaned, sort_keys=True)
    leaked = [
        value
        for value in [
            "alex@example.com",
            "sk-test123456789abcdef",
            "testBearerToken123456789",
            "hunter2",
            "supersecretvalue",
            "tok_live_1234567890abcdef",
        ]
        if value in cleaned_text
    ]
    if leaked:
        return "FAIL", f"secret leaked: {leaked[0]}"
    usage = cleaned.get("usage", {})
    if usage.get("input_tokens") != 123 or usage.get("output_tokens") != 45:
        return "FAIL", "token counts were redacted"
    return "PASS", ""


def _doctor_evaluation() -> tuple[str, str]:
    report = evaluate_cases()
    required = {"fixture_accuracy", "low_confidence_rate", "fixture_cases"}
    missing = required - set(report)
    if missing:
        return "FAIL", f"evaluation missing {', '.join(sorted(missing))}"
    if report["fixture_cases"] == 0:
        return "FAIL", "no fixture cases found"
    if report['fixture_cases'] != 6 or report.get('healthy_cases', 0) < 8:
        return "FAIL", "required positive/healthy corpus is incomplete"
    if report.get("case_errors") or report.get("unscored_cases"):
        return "FAIL", "evaluation contains errors or unscored cases; run agentlens evaluate for details"
    if report["fixture_accuracy"] < 1.0 or report.get('overall_accuracy', 0) < 1.0:
        return "FAIL", "positive or healthy regression expectations failed"
    return "PASS", ""


def _doctor_tool_selection_run() -> dict[str, Any]:
    # Prefer the real fixture so the doctor tests the same data as evaluate.
    _fixture_path = Path(__file__).resolve().parent / "tests" / "phase2_runs" / "phase2_tool_selection.json"
    if _fixture_path.exists():
        try:
            return json.loads(_fixture_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    # Fallback inline fixture when tests/ directory is not present.
    return {
        "run_id": "agentlens_doctor_tool_selection",
        "name": "doctor_tool_selection",
        "status": "error",
        "spans": [
            {
                "type": "llm_call",
                "provider": "anthropic",
                "model": "claude-3-5-sonnet-latest",
                "input_messages": [
                    {
                        "role": "user",
                        "content": "Find the renewal status for customer:alex using local records.",
                    }
                ],
                "tools": [
                    {"name": "search_web", "description": "find info about a topic"},
                    {"name": "query_db", "description": "find info about a topic"},
                ],
                "response_content": [
                    {
                        "type": "text",
                        "text": "Both tools look similar, so I will use search_web.",
                    },
                    {
                        "type": "tool_use",
                        "name": "search_web",
                        "input": {"query": "customer:alex renewal status"},
                    },
                ],
                "usage": {"input_tokens": 100, "output_tokens": 30},
            },
            {
                "type": "tool_call",
                "tool_name": "search_web",
                "input": {"query": "customer:alex renewal status"},
                "output": {
                    "status": "error",
                    "error": "Customer records are only available in query_db.",
                },
            },
        ],
    }


def _anonymize_value(value: Any) -> Any:
    return anonymize(value)


if __name__ == "__main__":
    main()
