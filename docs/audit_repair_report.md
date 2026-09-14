# AgentLens Audit Repair Report

Date: 2026-09-13 (America/Chicago). Scope: the 50-item release-safety audit.
Results below describe the repaired working tree, not the currently published package.

## 1. Overall Status

**READY** for beta use of the documented, tested capture/diagnosis scope.
No confirmed P1 from this audit remains unresolved in that scope. This is not
approval to publish automatically, a security certification, or evidence that
real developers find the diagnoses useful.

All 50 findings have an explicit disposition below. Scope corrections for
LangGraph, raw HTTP and Node parity are intentional remedies permitted by the
audit, not claims that unsupported functionality was implemented. The full hosted
CI matrix has not run; Python 3.11 and Node 20 remain CI verification gates before
a release. Python 3.9/3.10/3.12 clean-wheel checks passed locally.

Real external users: 0 reported. Customer traces: 0 reported. Payment signals:
0 reported. Generalization accuracy and confidence calibration remain unknown.
The two OSS cases are developer-operated fake-model workflows, not customer runs.

## 2. Findings Resolved

Paths are repository-relative. Test files are under `tests/` unless marked Node.
Line numbers refer to this working tree, not the older audit checkout. FIXED means
the finding was repaired or its false public claim corrected and checked; it does
not mean every possible provider configuration or sensitive-data format is covered.

| ID | Finding | Severity | Status | Files changed / functions | Regression test | Resolution |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Timeline script injection | P1 | FIXED | agentlens_engine/timeline.py:31 `_embed`, `generate_html` | test_security_regressions.py::test_script_boundaries; test_release_edges.py::test_canonical_prompt_timeline_and_impact | JSON escapes HTML delimiters before embedding; one-pass template substitution. |
| 2 | Shared credential and PII policy | P1 | FIXED | agentlens_core/privacy.py; agentlens.py:393; server/app.py | test_security_regressions.py (redaction, residual, escaped fragments); test_server_privacy.py | One normalized-key/redaction/scanning policy covers nested documents, quoted/escaped JSON fragments, complete bearer credentials and URL credentials. |
| 3 | Implicit remote diagnosis | P1 | FIXED | agentlens_engine/diagnose.py:24 `diagnose_run`; agentlens.py:290 | test_diagnosis_regressions.py::test_env_does_not_enable_remote; test_remote_opt_in.py | Local by default regardless of keys; explicit provider option, redacted compact input. |
| 4 | Run-ID traversal | P1 | FIXED | agentlens_core/storage.py:15 `safe_path`; agentlens_sdk/collector.py:644 | test_security_regressions.py::test_reject_export_traversal; test_release_edges.py::test_concurrent_writes_and_symlink_containment | Identifier validation plus resolved containment; load/export share checks. |
| 5 | OpenAI streaming | P1 | FIXED | agentlens_sdk/streams.py; agentlens_sdk/collector.py:476 | test_provider_protocols.py; test_provider_matrix.py (Responses, errors, cancellation) | Incremental sync/async wrappers preserve iteration and classify completion, early close, transport errors and cancellation. |
| 6 | Transparent provider clients | P1 | FIXED | agentlens_sdk/collector.py:436 `_patch_providers`, `_instrument_resource` | test_provider_protocols.py; test_provider_matrix.py | Patch resource methods instead of replacing constructors; test aliases, ordinary subclass, contexts, clones and custom transports. |
| 7 | Tool-result idempotency | P1 | FIXED | agentlens_sdk/collector.py:237 `_find_tool_span`, `record_tool_result`; agentlens_core/trace.py | test_trace_contract.py::test_idempotent_results_and_none_completion | Stable call IDs distinguish retries from result updates; completion does not depend on non-null output. |
| 8 | OpenAI tool normalization | P1 | FIXED | agentlens_sdk/collector.py:330,417; agentlens_core/trace.py | test_provider_protocols.py::test_sync_alias_context_clone_and_tools; test_provider_matrix.py::test_responses_sync_context_and_results | Correlate Chat role=tool and Responses function_call_output by ID. |
| 9 | Provider context preservation | P1 | FIXED | agentlens_sdk/collector.py:498 `_call_context`; agentlens_core/trace.py | test_provider_protocols.py::test_anthropic_system_and_error; test_provider_matrix.py | Preserve system, instructions, continuation IDs, normalized content and tool is_error. |
| 10 | Cancellation and lifecycle | P1 | FIXED | agentlens_sdk/collector.py:109 `run`; agentlens_sdk_ts/src/index.ts `run`, `saveRun` | test_trace_contract.py; test_beta_safety.py; Node persistence cleanup and cancellation tests | Await async functions; preserve cancellation; independent context reset; save/cleanup failures do not replace application results. |
| 11 | LangGraph compatibility | P2 | FIXED | agentlens_sdk/langgraph.py; README.md | test_langgraph_protocols.py (real compiled LangGraph 0.6.11) | Correct invoke/ainvoke and explicit updates-mode capture; configured wrappers preserved; unsupported modes explicitly excluded. |
| 12 | Node capture and package exports | P1 | FIXED | agentlens_sdk_ts/src/index.ts, package.json, package-lock.json, tests/ | Node tests/package.cjs and tests/types.ts via npm test | Built CJS/ESM-import-compatible output, declarations, options/APIPromise, tool IDs, concurrent runs; no streaming or Responses parity claim. |
| 13 | State drift false positive | P1 | FIXED | agentlens_engine/classifier.py:173 `_state_drift`; corpus/healthy/weather.json | test_diagnosis_regressions.py::test_healthy_abstention; packaged evaluation | Require explicit original goal, deviation and failed outcome; weather vocabulary alone is insufficient. |
| 14 | Context pollution false positive | P1 | FIXED | agentlens_engine/classifier.py:158 `_context_pollution`; corpus/healthy/conflicting_reports.json | test_diagnosis_regressions.py::test_healthy_abstention; packaged evaluation | Require incompatible instruction evidence affecting the goal, not legitimate discussion of conflicting reports. |
| 15 | Polling mistaken for loops | P1 | FIXED | agentlens_engine/classifier.py:137 `_loop`; corpus/healthy/polling.json | test_diagnosis_regressions.py::test_recovered_retries_are_not_a_loop; test_healthy_abstention | Use distinct failed call IDs, unchanged arguments/results, terminal failure and no recovery; repeated successes do not establish a loop. |
| 16 | Manufactured overflow evidence | P1 | FIXED | agentlens_engine/preprocess.py; classifier.py:199 `_overflow`; corpus/healthy/long_*.json | test_diagnosis_regressions.py::test_healthy_abstention | Truncation warnings live outside original evidence; only actual missing context and outcome evidence can support overflow. |
| 17 | Tool-selection false positives | P1 | FIXED | agentlens_engine/classifier.py:116 `_tool_selection`; corpus/healthy/search_records.json, partial.json | test_diagnosis_regressions.py::test_healthy_abstention | Require an actual routing error naming another available tool; no search/query-name inference or incomplete-run guessing. |
| 18 | Original span identity | P1 | FIXED | agentlens_core/trace.py:119; preprocess.py; timeline.py; impact.py; agentlens.py:649 | test_diagnosis_regressions.py::test_original_step_and_causal_precedence; test_release_edges.py::test_canonical_prompt_timeline_and_impact | Preserve span_id and original_index through filtering, deduplication, diagnosis and views. |
| 19 | Invalid model diagnosis accepted | P1 | FIXED | agentlens_engine/classifier.py:40 `validate_diagnosis`; diagnose.py | test_engine_boundaries.py::test_grounded_validation_all_invalid_types; test_diagnosis_regressions.py::test_reject_bad_llm_schema | Validate enum, finite scores, types, existing original step/tool and exact quoted field evidence; reject invented references. |
| 20 | Hallucination false accusations | P1 | FIXED | agentlens_engine/hallucination.py; agentlens_core/trace.py:79 | test_engine_boundaries.py::test_hallucination_negation_and_field_association; test_schema_additional_properties | Check negation, explicit entity/field relationships, normalized response text and JSON Schema additionalProperties semantics. |
| 21 | Confidence and causal arbitration | P1 | FIXED | agentlens_engine/classifier.py:93,103; agentlens.py:290 | test_diagnosis_regressions.py::test_original_step_and_causal_precedence; test_healthy_abstention | Unknown is a real abstention; retain candidate evidence and prefer the earliest supported cause; label scores uncalibrated. |
| 22 | Generic replacement of valid fixes | P2 | FIXED | agentlens_engine/diagnose.py; agentlens_engine/fixes.py | test_remote_opt_in.py::test_redacted_request_bounded_retry_and_grounded_fix_preserved | Retain a validated remote fix; local templates cite the actual step/tool without web-specific assumptions. |
| 23 | Source/package drift | P1 | FIXED | pyproject.toml; CHANGELOG.md; MANIFEST.in | tests/artifact_smoke.py on built 0.1.3 wheel | Prepare unreleased 0.1.3, build wheel/sdist, verify the installable artifact rather than claiming the published release was updated. |
| 24 | Missing installed fixtures | P1 | FIXED | agentlens_engine/corpus/; evaluate.py:24; pyproject.toml package-data | tests/artifact_smoke.py; test_engine_boundaries.py::test_shared_category_and_corpus | Bundle 6 positive and 8 healthy resources; doctor rejects a missing corpus; OSS cases remain separate. |
| 25 | Incomplete CI | P2 | FIXED | .github/workflows/ci.yml; pyproject.toml | Local tests/artifact checks; workflow inspection | CI configured for Python 3.9/3.10/3.11/3.12, wheel smoke, local provider mocks, security/negative tests, lint/types and Node 20/22. Hosted execution not run. |
| 26 | Broken real-SDK example dispatch | P1 | FIXED | examples/openai_broken_agent.py; anthropic_broken_agent.py; shared_tools.py | test_example_dispatch.py; both offline example commands | Read actual SDK objects and dispatch the selected tool with its actual arguments. |
| 27 | Malformed files cause tracebacks | P1 | FIXED | agentlens_core/trace.py:211 `read_run`; collector.py:629; agentlens.py:56 | test_cli_boundaries.py::test_bad_files_and_missing_run_exit; test_trace_contract.py | Validate shape/encoding/size at load boundaries; actionable nonzero CLI errors, without raw tracebacks. |
| 28 | Incorrect success exit codes | P2 | FIXED | agentlens.py:56 `main`, `_print_doctor`, `_dispatch` | test_cli_boundaries.py::test_failed_health_commands_exit_nonzero; test_bad_files_and_missing_run_exit | Missing/corrupt input and failed required health/evaluation checks exit nonzero. |
| 29 | Demo makes implicit requests | P1 | FIXED | agentlens.py:904 `_run_demo`; diagnose.py | test_release_edges.py::test_demo_offline_with_keys; artifact smoke | Deterministic local demo remains offline with fake provider keys and provider/network traps. |
| 30 | Unbounded remote diagnosis | P2 | FIXED | agentlens_engine/diagnose.py:56 `_diagnose_with_llm`; README.md | test_remote_opt_in.py | Three-second connect, at-most-ten-second read, zero SDK retries, one extra invalid-JSON attempt; oversized request never transmits. |
| 31 | False browser-open success | P2 | FIXED | agentlens.py:625 `_open_timeline` | test_cli_boundaries.py::test_headless_view_is_honest | Honor webbrowser.open false; show generated file path instead of claiming a browser opened. |
| 32 | Watch change handling | P2 | FIXED | agentlens_core/watch.py `SnapshotWatcher`; agentlens.py:1015 | test_engine_boundaries.py::test_watch_same_size_replace_shrink_and_missing | Parse changed saved snapshots only; handle replacement, shrinking, disappearance and same-size timestamp changes; reject invalid intervals. |
| 33 | Prompt viewer step mismatch | P2 | FIXED | agentlens.py:649 `_print_prompt_viewer` | test_release_edges.py::test_canonical_prompt_timeline_and_impact | Filter/render by original span index, not a separate LLM-call ordinal. |
| 34 | Stitch recursion cycles | P2 | FIXED | agentlens.py:853 `_print_stitch` | test_cli_boundaries.py::test_stitch_cycle | Visited-run tracking emits a cycle warning instead of recursive failure. |
| 35 | Partial JSON writes | P1 | FIXED | agentlens_core/storage.py:25 `atomic_write`; collector.py:295; Node saveRun | test_cli_boundaries.py::test_atomic_failure_keeps_old_content; test_release_edges.py::test_concurrent_writes_and_symlink_containment | Same-directory restricted temporary files, flush/fsync and atomic replacement; shared paths have last-whole-snapshot semantics. |
| 36 | Partial runs shown completed | P1 | FIXED | agentlens_engine/status.py; collector.py:302; Node run | test_cli_boundaries.py::test_partial_status_is_not_completed_or_healthy; test_trace_contract.py; Node pending-tool test | Keep running/partial/cancelled/unknown distinct; pending calls do not establish completion. |
| 37 | Ingestion drops metadata | P2 | FIXED | server/app.py; agentlens_core/trace.py | test_server_privacy.py::test_metadata_round_trip_and_partial_state | Persist validated run fields including ended_at, parent_run_id and metadata. |
| 38 | Misleading cost accounting | P2 | FIXED | agentlens.py:1064 `_summarize_run`, `_merge_stats`; impact.py; Python/Node pricing | test_engine_boundaries.py::test_cost_is_llm_only_and_unknown; Node cost test | Use explicit LLM costs, distinguish unknown from zero, avoid token-alias double counting and arbitrary model-prefix pricing; stats includes all loaded runs. |
| 39 | SDK imports full application | P2 | FIXED | agentlens.py:39 `_lazy`; agentlens_sdk/__init__.py | test_release_edges.py::test_import_without_engine_or_providers; clean no-deps wheel | Lazy command-only engine imports; basic capture imports without engine command modules or optional providers. |
| 40 | Different category inference by view | P2 | FIXED | agentlens_engine/clustering.py; similarity.py; classifier.py | test_engine_boundaries.py::test_shared_category_and_corpus | Clustering/similarity consume canonical offline diagnosis rather than independent category guesses. |
| 41 | Mixed responsibilities | P2 | FIXED | agentlens_core/; agentlens_sdk/streams.py; agentlens.py:65 `_parser`; classifier.py | Full Python tests, lint and type checks | Extract shared privacy/storage/normalization/watch, streaming protocols, parser and focused evidence rules; do not relocate public packages. |
| 42 | Decorator erases callable type | P2 | FIXED | agentlens_sdk/collector.py:109 `run`, TypeVar F | test_beta_safety.py; mypy over 23 source files | Preserve the input callable type for sync/async decorators instead of returning an untyped callable. |
| 43 | Missing common schemas | P1 | FIXED | agentlens_core/trace.py:14-211; classifier.py:40; server/app.py | test_trace_contract.py; test_engine_boundaries.py; test_server_privacy.py | Shared typed span/run/evidence/diagnosis/status contracts plus strict runtime file/ingestion validation. |
| 44 | Stale maintenance checks | P2 | FIXED | agentlens.py:65,1265; pyproject.toml; touched Python modules | ruff; mypy; doctor imports | Remove unused helpers/imports and derive command checks from the actual parser rather than a stale list. |
| 45 | Unsupported zero-FP claim | P2 | FIXED | README.md; index.html; docs/release_verification.md | 8 healthy fixtures; explicit raw-count evaluation; literal claim review | Report the small corpus result, not a universal or population false-positive claim. |
| 46 | Universal LangGraph claim | P2 | FIXED | README.md; index.html; agentlens_sdk/langgraph.py | test_langgraph_protocols.py; claim review | Limit node claims to explicit top-level updates on supported post-init compiled graphs. |
| 47 | Raw API interception claim | P2 | FIXED | README.md; index.html; Node README.md | Resource-method patch inspection; provider protocol tests | Remove universal raw HTTP and arbitrary framework interception claims. |
| 48 | Unconditional local privacy claim | P1 | FIXED | README.md; index.html; demo/terminal_demo.html; diagnose.py | test_remote_opt_in.py; test_demo_offline_with_keys; claim review | Explain default local processing versus explicit redacted provider transmission and best-effort anonymization. |
| 49 | Incorrect optional PII setup | P2 | FIXED | agentlens_core/privacy.py `_name_model`; README.md | test_security_regressions.py::test_optional_name_model_setup_hint | Correct runlens[pii] extra and separate en_core_web_sm install hint; model itself not installed/live-tested. |
| 50 | Quickstart persistence promise | P2 | FIXED | README.md; Node README.md; examples/ | test_beta_safety.py; example smoke; artifact smoke | Distinguish two-line instrumentation from run grouping/persistence; add an activated environment to avoid stale global CLI resolution. |

Baseline recorded before repairs: 6 Python tests passed, six positive fixtures
and two OSS cases matched, source doctor passed, and a 0.1.2 wheel/sdist built.
A clean-environment baseline wheel run was not completed in this repair. The
new healthy-negative and protocol tests are additional evidence, not a claim that
the old six fixtures measured reliability.

Two legacy fixture corrections preserve the actual failure: each loop retry now
has a distinct provider call ID; the overflow expected step is the original
context-loss step 2, not the downstream final error at step 4. Expected diagnoses
are evaluation inputs only; they are not passed to the classifier as an oracle.

## 3. Diagnosis Reliability

Final source command: `python -B agentlens.py evaluate`, offline.

| Metric | Checkout | Clean installed wheel outside checkout |
| --- | --- | --- |
| Synthetic positive fixtures | 6 | 6 |
| Developer-operated OSS positive cases | 2 | 0 |
| Healthy/partial abstention cases | 8 | 8 |
| False positives | 0/8 | 0/8 |
| False negatives on positive cases | 0/8 | 0/6 |
| Category matches | 16/16 | 14/14 |
| Original failed-step matches | 16/16 | 14/14 |
| Abstentions | 8/16 | 8/14 |
| Low-confidence rate | 50% | 57% rounded |
| Most failed category | none | none |
| Mean local runtime in final observed runs | 0.32 ms | 0.21-0.35 ms |

Each of the six advertised categories has one packaged positive case. Provider/
framework labels in the checkout: Anthropic 4/4, OpenAI 2/2, LangGraph fake model
1/1, CrewAI custom model 1/1, unspecified 8/8. These are regression labels, not
live-provider accuracy. Percentages on this tiny selected corpus do not estimate
accuracy on unseen agents.

Eight unknown results are expected abstentions, not failures suppressed by score
changes. Evidence guards distinguish healthy polling, repeated success, customer
search tools, legitimate conflicting reports, weather answers, long output,
long runs and partial execution.

Local rules remain narrow. In particular, context pollution/state drift require
explicit goal/instruction/outcome evidence; many subtle semantic failures will
abstain. A quoted observation proves that the text exists, not that a remote
model's causal interpretation is true. No evidence establishes that remote
diagnosis is generally better than local rules.

## 4. Provider Compatibility

Python tests ran with OpenAI 2.41.0 and Anthropic 0.107.0, using actual SDK parsers
and deterministic local HTTP transports. No paid provider call was made.

| Provider/API | Sync | Async | Streaming | Tool calls/results | Context manager/config clone |
| --- | --- | --- | --- | --- | --- |
| Python OpenAI Chat Completions | PASS | PASS | Sync early-close and async completion PASS; generic error/cancel wrapper tests PASS | ID-based selection and role=tool result PASS | Sync/async contexts and with_options PASS; ordinary subclass/alias/custom URL/transport PASS |
| Python OpenAI Responses | PASS | PASS | Sync/async response.completed event PASS | function_call and function_call_output PASS | Sync/async contexts PASS; a Responses-specific clone combination was not separately tested |
| Python Anthropic Messages | PASS | PASS | create(stream=True) and messages.stream managers PASS, sync/async | Selection, system and tool-result error PASS | Sync/async contexts and with_options PASS |
| Node OpenAI Chat | Awaited promise PASS | Promise/ALS isolation PASS | Not supported; pass-through warning, not captured | Selection, automatic role=tool result and idempotent manual update PASS | Alias/subclass/custom fetch/options/APIPromise PASS; no separate client-clone matrix |
| Node Anthropic Messages | Awaited promise PASS | Shared promise wrapper | Not supported | Automatic selection PASS; shared result correlation implemented, not a separate Anthropic result test | Custom fetch PASS; no separate clone matrix |

LangGraph 0.6.11 tests use compiled graphs: invoke/ainvoke aggregate capture,
top-level updates-mode node capture, values-mode negative and configured wrapper.
Compile after patching. Precompiled graphs, batch, subgraphs and multi-mode node
attribution are not promised.

Custom transports preserve provider configuration; this is not a live proxy test.
Arbitrary method overrides, raw HTTP, beta endpoints, detached tasks, and combinations
with other instrumentation are not guaranteed. Close or fully consume Python streams
inside the run. Unclosed abandoned streams cannot guarantee late persistence.

## 5. Security Verification

- Timeline tests pass for lowercase/uppercase/mixed-case script closers, nested tool
  outputs/errors, ordinary HTML delimiters, ampersands and Unicode separators.
  Embedded JSON round-trips without a literal HTML opening delimiter.
- Shared credential policy passes normalized key variants, nested/quoted JSON,
  escaped fragments embedded in prose, complete bearer suffixes, URL credentials,
  and residual scanning. Numeric input_tokens/output_tokens remain intact.
- The final escaped-fragment regression initially failed ten subcases. Redaction
  and residual detection now share fragment normalization; ingestion also rejects
  the escaped secret and accepts the redacted equivalent.
- Traversal and resolved symlink-containment regressions pass. Atomic writes use
  restrictive temporary-file permissions and preserve the previous complete file
  on an injected replacement failure.
- Provider keys alone do not trigger remote diagnosis or demo requests. Explicit
  remote requests are redacted, compact and bounded; oversized inputs do not transmit.
- Optional person-name model setup warning is tested. A real downloaded spaCy model
  was not exercised. Names outside built-in keyed fields still require manual review.
- Raw local capture intentionally preserves debugging inputs, which may include
  secrets. No universal PII-removal guarantee is made. Unknown encodings and private
  business information need manual review before export.
- The pre-existing server remains unauthenticated and is not approved for public
  internet exposure. The repair aligns ingestion validation; it adds no hosted service.

## 6. Packaging Verification

Python source version: **0.1.3** (unreleased).
Wheel: `runlens-0.1.3-py3-none-any.whl`; metadata version: **0.1.3**.
Sdist: `runlens-0.1.3.tar.gz`.
Local final build directory: `/tmp/agentlens-release-final/`.
No package was published.

Built with `python -m build --no-isolation --outdir /tmp/agentlens-release-final`.
For each installed interpreter, `tests/artifact_smoke.py` creates a fresh virtual
environment, installs only the wheel with `--no-deps`, and runs outside the checkout:

| Interpreter | Import/help | Doctor | Offline demo with keys set | Evaluate | List/show/diagnose/anonymize/feedback |
| --- | --- | --- | --- | --- | --- |
| Python 3.9.20 | PASS | healthy | PASS | 14/14 | PASS |
| Python 3.10.7 | PASS | healthy | PASS | 14/14 | PASS |
| Python 3.12.7 | PASS | healthy | PASS | 14/14 | PASS |
| Python 3.11 | Not installed locally | Not run | Not run | Not run | CI configured |

Wheel inspection asserts 14 JSON corpus resources, actual site-packages import
location, correct distribution version, and absence of tests, server and private
run/log files. The core CLI imports without optional providers.

Node package version remains 0.1.0; no publication occurred. A clean temporary
checkout of the Node source plus the exact lockfile passed `npm ci`, `npm test`
and `npm pack --dry-run --json`. The pack list has six files: README, package.json,
dist/index.js, its map, dist/index.d.ts and its map. Require and ESM import target
existing output; a consumer type-check resolves the exported declarations.

## 7. Tests

| Verification | Passed | Failed | Skipped |
| --- | --- | --- | --- |
| Python unittest discovery, Python 3.9.20 | 64 | 0 | 0 |
| Node built-output tests, Node 22.17.1 | 6 | 0 | 0 |
| Clean Python wheel interpreter runs | 3 | 0 | 0 |

Python final suite runtime: 7.521 seconds. This includes real-SDK local transport
tests, three actual LangGraph tests, runtime/server security checks and subprocess
CLI tests. An upstream LangGraph pending-deprecation warning remains.

Ruff: all checks passed on the configured E4/E7/E9/F/I rules.
Mypy: no issues in 23 explicitly checked project source files; third-party imports
are skipped, not claimed fully type-checked. Node verification includes TypeScript
compilation and consumer typing before the six runtime tests.

Both broken-agent examples ran offline and saved traces with three spans.
The clean-wheel CLI chain tested readable details, specific diagnosis/source/step,
anonymized output and feedback questions. No live authentication/billing/network
workflow was run.

Earlier failures were not discarded: escaped secret cases failed before their
fix; three added Node checks failed before pending-run, cost and cleanup repairs.
Node tests against the checkout's old generated dependencies also timed out during
a bare provider import, before assertions. A clean exact-lockfile installation
passed all six tests. Refreshing the checkout with `npm ci --ignore-scripts
--no-audit --no-fund` resolved that issue; its normal `npm test` then passed all six
tests in 189.724 ms. Earlier failed runs are not counted as passing runs.

Hosted CI has not executed this uncommitted change. The workflow includes Python
3.9/3.10/3.11/3.12 and Node 20/22 with artifact, security, negative and provider tests.

## 8. Public Claims Changed

- Replace universal root-cause certainty with supported original-step evidence or
  insufficient evidence; scores are not calibrated probabilities.
- Replace universal zero false positives and implied user benchmarks with reproducible
  raw corpus counts, including healthy cases and explicit fake-model OSS labels.
- Clarify that all six categories are narrow evidence rules, not general intent
  inference or arbitrary factual verification.
- Separate local default diagnosis from opt-in remote provider transmission; describe
  selected prompts/tool definitions/input/output/error content, redaction and limits.
- Remove unconditional no-data-leaves language from the README/site/demo where remote
  use is offered; retain the precise offline-demo guarantee.
- Describe anonymization as best effort, with manual review and optional name-model
  installation; do not imply all private content is removed.
- Narrow all-nodes/framework claims to tested LangGraph compile/mode behavior.
- Remove raw-API and arbitrary framework interception claims; specify SDK resource
  methods, versions and unsupported overrides/endpoints.
- Remove Node/Python parity implications; specify Node non-streaming scope and real
  CJS/ESM-compatible emitted files.
- Explain instrumentation versus grouping and persistence: init alone does not save
  a grouped run; decorators/save are required.
- Explain awaited child tasks and consumed/closed streams; no detached-task guarantee.
- Define watch as changed saved snapshots, not live event streaming.
- Label pricing historical, unknown pricing as unknown, and post-failure usage as
  not proven waste; aggregate all loaded runs for all-run stats.
- Label website/demo illustrative scores/costs as illustration, not measured outcomes.
- State 0.1.3 is prepared but unpublished; the public package may differ.
- Add a dedicated virtual environment and correct optional runlens[pii]/model commands
  so onboarding does not accidentally use a stale global CLI.
- Document the unauthenticated server boundary and remaining beta/user validation gap.

## 9. Remaining Limitations

1. This is a scoped beta, not evidence of trust from real users or a measured
   real-world accuracy rate. Do not move to a market-validation-complete phase.
2. Python 3.11 and Node 20 are configured in CI but not locally executed; Node 18
   and Python versions beyond the tested matrix are not validated by this report.
   Require hosted CI before releasing. Provider versions outside the constrained
   tested minors may change protocols.
3. A local PATH mismatch selects an older Python 3.13 global CLI. That executable
   returned zero fixtures and a failed doctor check. The repaired source and fresh
   wheel both pass; use the README's activated virtual environment.
4. The checkout contains three legacy malformed run files (two with invalid usage,
   one with a non-object span). Listing shows valid runs and reports these errors
   with a nonzero status. Exact/prefix lookup of a valid file still works. These
   private historical files were not modified or silently migrated.
5. The old Node dependency directory exhibited import stalls. The identical locked
   dependencies installed under /tmp passed; refreshing the checkout dependencies
   restored its normal six-test pass too. The exact original filesystem cause was
   not conclusively identified; no dependency versions were changed by the refresh.
6. Remote validation checks schema/references/quoted evidence, not semantic truth.
   Model quality, real-provider behavior, and general confidence calibration are
   unmeasured. Sparse or subtle failures may remain unknown.
7. Redaction cannot guarantee removal of unknown encodings, arbitrary names or
   proprietary facts. Local raw traces must be protected; review exports manually.
8. Atomic replacement prevents torn JSON, but shared destinations are last-complete-
   snapshot wins, not merge storage. It is not a guarantee against every filesystem/
   power-loss scenario. Detached tasks and abandoned streams remain unsupported.
9. Captured error spans conservatively affect legacy run error status even if an
   application catches an error. Diagnosis guards distinguish recovery separately.
10. Some long CLI rendering/template functions remain. Shared responsibilities were
    extracted for correctness; this was not a wholesale CLI/package rewrite.
11. The optional person-name model and live proxy/client combinations were not tested.
    Node Responses/streaming capture and full framework-node parity remain unsupported.
12. The legacy per-case confidence_min/confidence_max fields are not scored by the
    category/step evaluator. Its printed matches are not a confidence-range calibration
    result. The score is explicitly uncalibrated.

## 10. Git Status

Branch: `redesign-website`.
HEAD: `31948877d681fb298d38594f876edfd5b7a0a6d4`.
The branch/HEAD changed externally from the initially observed
`make-server-standalone-project` / `34f3d23`; this repair did not switch branches.
No commit, push, merge, release or publication was performed. Nothing is staged.

Pre-existing `server/README.md` and untracked `server/requirements.txt` were
preserved, not included as repair work. Existing website layout changes were
preserved; only factual claim text was adjusted. No tracked file was deleted.

Private work logs, .agentlens data, .env, generated run/anonymized JSON, build/cache
and egg-info files remain ignored and are absent from tracked/staged file checks.
The worktree is intentionally dirty with the repair below; it is not committed.

```text
 M .github/workflows/ci.yml
 M .gitignore
 M README.md
 M agentlens.py
 M agentlens_engine/classifier.py
 M agentlens_engine/clustering.py
 M agentlens_engine/diagnose.py
 M agentlens_engine/evaluate.py
 M agentlens_engine/fixes.py
 M agentlens_engine/hallucination.py
 M agentlens_engine/impact.py
 M agentlens_engine/preprocess.py
 M agentlens_engine/similarity.py
 M agentlens_engine/status.py
 M agentlens_engine/timeline.py
 M agentlens_sdk/__init__.py
 M agentlens_sdk/collector.py
 M agentlens_sdk/langgraph.py
 M agentlens_sdk/pricing.py
 M agentlens_sdk_ts/package.json
 M agentlens_sdk_ts/src/index.ts
 M demo/terminal_demo.html
 M examples/anthropic_broken_agent.py
 M examples/openai_broken_agent.py
 M examples/shared_tools.py
 M index.html
 M pyproject.toml
 M server/README.md
 M server/app.py
 M tests/generate_phase2_runs.py
 M tests/phase2_runs/phase2_loop.json
 M tests/test_beta_safety.py
?? CHANGELOG.md
?? MANIFEST.in
?? agentlens_core/__init__.py
?? agentlens_core/privacy.py
?? agentlens_core/storage.py
?? agentlens_core/trace.py
?? agentlens_core/watch.py
?? agentlens_engine/corpus/healthy/conflicting_reports.json
?? agentlens_engine/corpus/healthy/long_answer.json
?? agentlens_engine/corpus/healthy/long_run.json
?? agentlens_engine/corpus/healthy/partial.json
?? agentlens_engine/corpus/healthy/polling.json
?? agentlens_engine/corpus/healthy/repeated_success.json
?? agentlens_engine/corpus/healthy/search_records.json
?? agentlens_engine/corpus/healthy/weather.json
?? agentlens_engine/corpus/positive/phase2_cascade.json
?? agentlens_engine/corpus/positive/phase2_context_pollution.json
?? agentlens_engine/corpus/positive/phase2_loop.json
?? agentlens_engine/corpus/positive/phase2_overflow.json
?? agentlens_engine/corpus/positive/phase2_state_drift.json
?? agentlens_engine/corpus/positive/phase2_tool_selection.json
?? agentlens_sdk/streams.py
?? agentlens_sdk_ts/README.md
?? agentlens_sdk_ts/package-lock.json
?? agentlens_sdk_ts/tests/package.cjs
?? agentlens_sdk_ts/tests/types.ts
?? docs/release_verification.md
?? server/requirements.txt
?? tests/artifact_smoke.py
?? tests/test_cli_boundaries.py
?? tests/test_diagnosis_regressions.py
?? tests/test_engine_boundaries.py
?? tests/test_example_dispatch.py
?? tests/test_langgraph_protocols.py
?? tests/test_provider_matrix.py
?? tests/test_provider_protocols.py
?? tests/test_release_edges.py
?? tests/test_remote_opt_in.py
?? tests/test_security_regressions.py
?? tests/test_server_privacy.py
?? tests/test_trace_contract.py
?? docs/audit_repair_report.md
```
