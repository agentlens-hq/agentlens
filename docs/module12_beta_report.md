# AgentLens Modules 1 + 2 Beta Completion Report

**Reading guide:** sections 1-15 preserve the September 16 audit as recorded.
The September 17 remote-evidence repair is appended in section 16; the current
pre-PR classification and separate readiness gates are in section 17. Earlier
failing-test statements and no-commit snapshots are historical, not erased.

Audit date: September 16, 2026 (America/Chicago).
Base commit: `59ce36159f09dd059d13dc7b0b4bba1ec87f840f`.
Actual checkout: `/Users/abishekkumargiri/Desktop/agentlens:` (trailing colon).
The path without that colon in the request is not this working directory.

## 1. Executive Summary

**MODULE 1 BETA COMPLETE: NO**

**MODULE 2 BETA COMPLETE: NO**

**EXTERNAL BETA READY: NO** for the complete supported contract requested here.
Supervised offline exploration is possible, but is not the completed milestone.

The baseline checkout was clean, with no staged, modified, or untracked files.
All 95 pre-existing Python tests passed. This audit added targeted tests, found
real defects, and made bounded corrections without changing package architecture.
Final full Python verification is **107 passed, 1 failed**, not a green release.

The remaining failing test demonstrates that a model can assert a fabricated
loop at 0.99 confidence on a healthy single-tool run merely by quoting the word
`found`. `validate_diagnosis` accepts it. A real quote does not prove the proposed
explanation or fix. This is a P1 trust blocker for remote diagnosis.

Neither provider key is present in the environment. Live validation, four genuine
agent workflows, and independent external-developer feedback remain unperformed.
No credentials were searched for in private files or copied from attachments.
No live provider call, external outreach, deployment, or publication occurred.

## 2. Module 1 Capability Matrix

"Offline verified" means actual tests, not live API verification. See the
[support contract](module12_support.md) for the full integration/tool matrix.

| Capability | Python | TypeScript | Status | Verified | Notes |
| --- | --- | --- | --- | --- | --- |
| Named run capture | Sync/async decorator | Awaited callback | Implemented | Offline | `init` alone does not save a named run |
| OpenAI normal/tool calls | Chat + Responses | Chat | Implemented, not live verified | Offline SDK transports | Not arbitrary OpenAI endpoints |
| Anthropic normal/tool calls | Messages | Messages | Implemented, not live verified | Offline SDK transports | No universal provider traffic interception |
| Tool results | Next request or explicit record | Next request or explicit record | Partial/manual boundary | Offline | Final results may require manual recording |
| Tool execution and latency | Not automatic | Not automatic | Not implemented generally | Source audit | Selection is not execution |
| Model, prompts, schemas | Captured request fields | Captured request fields | Implemented | Offline | Hidden provider context is unavailable |
| Provider errors | Exceptions/cancellation | Rejections/AbortError | Implemented | Offline | Tool exceptions need enclosing run or explicit handling |
| OpenAI streaming | Sync/async Chat + Responses | No capture | Python implemented, not live verified | Offline | One reconstructed span, not each chunk |
| Anthropic streaming | Iterator + stream manager | No capture | Python implemented, not live verified | Offline | Consume/close inside run |
| Mid-stream transport errors | Captured | Unsupported streams | Partial | Offline | EOF without completion now marked partial |
| Token usage | Provider supplied | Provider supplied | Implemented | Offline | No invented missing usage |
| Latency | Request to end | Request to response | Implemented | Offline | Tool runtime not measured separately |
| Cost | Historical estimate | Historical estimate | Partial | Offline | Not exact billing; no Module 3 expansion |
| Memory/state | Explicit copied snapshots | Explicit copied snapshots | Manual | Python copy/privacy tests; Node source | No magical automatic state capture |
| State comparison | Replay diff | Python CLI on Node JSON | Implemented narrowly | Offline | Nested dictionaries; whole lists |
| Hierarchy | Nested runs/context propagation | Explicit parent context | Partial | Python nested/parallel tests; Node parallel tests | No distributed completeness |
| Local storage | Atomic JSON replacement | Atomic JSON replacement | Implemented | Concurrent/write-failure tests | Same destination is last-writer-wins |
| Inspection/timeline | CLI/local HTML | Python CLI on saved JSON | Implemented | CLI/HTML regression tests | No new UI built |
| Replay | Next/back/full/diff | Via Python CLI | Recorded inspection only | Offline | Never executes models/tools |
| Watch | Saved-snapshot polling | Saved-snapshot polling | Partial | Rotation/replace tests | Not live event streaming |
| Export/anonymize | Shared privacy module | Via Python CLI | Best effort | Hostile credential tests | Raw local files can contain secrets |
| Frameworks | Scoped LangGraph wrapper | No native wrappers | Partial | LangGraph 0.6.11 local tests | CrewAI/AutoGen/PydanticAI conditional passthrough |

### Architecture Map

- Public Python entry: `agentlens.py:27` (`__all__`); SDK implementation in
  `agentlens_sdk/collector.py:94` (`init`) and `:109` (`run`). Engine imports from
  the public entry are lazy; import without provider/engine dependencies is tested.
- Provider resource patches: `collector.py:436` / `:476`; call context at `:498`,
  capture at `:508`; original configuration/resource methods are retained.
- Tool request extraction: `collector.py:399` / `:417`; result correlation and
  updates: `:258` / `:330`. A logical tool request/result is one span, keyed by ID.
- Streaming: `agentlens_sdk/streams.py:10` (`Accumulator`), `:90` (`Stream`);
  Anthropic manager wrapper: `collector.py:573`.
- Framework instrumentation: `agentlens_sdk/langgraph.py:42` (`patch_langgraph`),
  `:70` (compiled wrapper). Precompiled/batch/subgraph modes are not covered.
- Node public API and patches: `agentlens_sdk_ts/src/index.ts`; AsyncLocalStorage,
  resource-method interception, manual `recordToolResult`/memory APIs.
- Canonical normalization: `agentlens_core/trace.py:119`; strict file boundary
  `:211` (20 MiB input limit). Run IDs, original indices and tool-result completion
  are preserved; there is no universal tool-execution span type or schema version.
- Storage: `agentlens_core/storage.py:25`; state comparison: `agentlens_core/state.py:8`.
- Timeline: `agentlens_engine/timeline.py:17`; CLI prompt/replay/stitch/watch in
  `agentlens.py`; polling implementation in `agentlens_core/watch.py`.
- Usage/latency summaries: `_summarize_run`, `_usage_counts` in `agentlens.py`;
  historical pricing: `agentlens_sdk/pricing.py`; post-failure usage: `impact.py`.
- Redaction/residual checks: `agentlens_core/privacy.py`; CLI anonymization and
  `upload prepare` write locally, not to a hosted service.

## 3. Module 1 Remaining Gaps

**BETA BLOCKER:** real provider validation is absent for every claimed Python
provider path, and Node has only local protocol verification. Do not label fake
HTTP transports or fake example clients as live validation.

**SHOULD FIX SOON:** in-flight calls have no persisted start span until completion;
unclosed/abandoned streams and hard process death can lose unsaved evidence.
`save_run()` is an explicit checkpoint, not automatic event durability.
See the concrete local atomic-checkpoint design in the support document. It was
deferred because correct concurrent mutation/finalization requires a lifecycle
change, not a one-line watcher patch.

**SHOULD FIX SOON:** recovered error history still makes SDK execution status
`error`; distinguish historical error events from terminal outcome in a follow-up.
The diagnosis recovery guard now prevents the specific goal-drift false positive,
but the run badge is still not a correctness judgment.

**SHOULD FIX SOON:** document/observe final tool-result recording during actual
onboarding. A new decorator was not introduced without evidence that it is needed.

**DEFER:** universal framework coverage, Node/Python parity, distributed tracing,
automatic memory interception, automatic execution replay, OTel dependency.

Parent/child checks cover parent -> child A -> grandchild, parallel child B,
handled child exception, running snapshot, completion and CLI tree. Missing child
files are not detectable without an independently recorded handoff. A never-saved
child remains invisible; a manually checkpointed child remains visibly running.

## 4. Module 2 Category Matrix

Pipeline: `normalize_run` -> `preprocess_run` -> all candidate rules -> earliest
original candidate step -> fix template -> schema/contradiction findings + impact
-> structural/evidence validation -> CLI. With explicit provider opt-in, a
redacted bounded prompt is tried before heuristic fallback.

Preprocessing retains at most 200 spans (first plus last 199), bounds strings and
objects, retains original IDs/indices and raw-value hashes, and collects schemas,
system context, final output and errors. It does not keep the last three spans in
unlimited detail. Omitted evidence can prevent diagnosis; it is not evidence that
the agent's own context window overflowed. Duplicates are normalized before rules.

| Category | Required evidence / failed step | Abstention rule | Regression coverage | Status |
| --- | --- | --- | --- | --- |
| tool_selection | Failed tool explicitly names required alternative; origin is that tool span | No explicit mismatch, successful identical retry, or contradictory destinations | Fixture, two OSS cases, expired-session controls, new conflict/multi-failure probes | Narrow implemented rule; no semantic intent inference |
| loop | Identical failed tool/input/output series plus terminal iteration/no-exit error; first failed call in series | Successful retry, progress, absent terminal proof, routine repetition | Fixture, single-tool/recovered/polling/justified retry | Defensible narrow series detector |
| cascade | Empty/explicitly flagged field consumed unchanged downstream; downstream error names same field; upstream step | Unrelated error, ordinary business text, changed values, downstream recovery | Fixture plus hostile field/value/hash regressions | Narrow structured propagation |
| context_pollution | Explicitly conflicting system instruction, matching response wording, confirming terminal error; instruction-bearing LLM step | Mere disagreement or absent terminal confirmation | Positive fixture, healthy conflicting reports | Partial: heavily dependent on explicit self-labeling |
| state_drift | User goal, explicit abandoned-goal response, confirming terminal error; goal-loss step | No stated loss, no terminal proof, or later model response after error | Fixture, new recovery and upstream precedence tests | Partial: cannot infer subtle drift |
| overflow | Earlier user message omitted, explicit context-loss response, terminal failure; affected LLM step | Long run alone, preprocessing truncation, previous_response_id/conversation, no terminal proof | Fixture, long-run/healthy controls | Partial: explicit context-loss probe only |
| schema / contradiction | Undeclared parameter in closed simple schema, missing required field, narrow same-entity fact contradiction | Open/composed schemas or no demonstrable entity/field relationship | Schema revisions, additionalProperties, negation and unrelated-number controls | Structural checks, NOT arbitrary hallucination detection |

Optional corroboration includes tool definitions, later error/response spans and
full-value digests. Tool descriptions alone do not prove wrong selection.
Fix templates name the observed tool/step and recommend routing, retry stop,
field validation, prompt cleanup, goal restoration or retained context. These
are suggestions; they are not empirically proven to resolve a user's issue.

All local positive RCA rules use 0.85; abstention uses 0. Separate schema scores
are 0.95/0.97 and contradiction scores 0.80. Remote scores are model-supplied,
validated only for finite numeric range. None are calibrated probabilities.

Candidate sorting is by original step. A same-step tie follows detector order
(context, drift, selection, cascade, overflow, loop), not learned causal ranking.
Tested: selection -> cascade selects selection; tool error -> loop selects first
failed attempt; drift -> wrong tool selects drift and reports selection secondarily.
Secondary categories do not establish that one candidate caused another.

### Unresolved P1: Remote Evidence Does Not Entail Cause

`agentlens_engine/classifier.py:40` (`validate_diagnosis`) checks schema, quoted
text and step/tool membership, but not whether those facts support the category,
explanation or fix. `agentlens_engine/diagnose.py:24` accepts that output as LLM
diagnosis. Reproducer: `tests/test_module12_trust.py:50`.

Expected: unknown/heuristic. Actual: `loop`, step 1, confidence 0.99, fabricated
retry-budget explanation and provider-switch fix on a healthy lookup.
This test remains failing, with no xfail, skip, score reduction or relabeling.

Minimum repair decision: either constrain model assertions to independently
supported category/step predicates and treat unsupported narrative as proposals,
or exclude remote diagnosis from the trusted beta contract until such a gate is
tested. Simply checking more quote syntax cannot solve entailment. A prompt-only
edit or extra self-grading LLM was not introduced as an unverified safety fix.
Existing source-label tests accept weak quoted evidence; they were not rewritten
to manufacture a green result. This needs a focused acceptance-contract repair.

Transport failure/timeout, invalid JSON, invalid category, nonexistent step,
nonfinite/out-of-range confidence and absent quoted evidence have existing tests.
Provider failure uses local fallback; invalid JSON has one retry. Payloads are
redacted and limited to 60 KB; no implicit remote call from available keys.
Transport timeout is not a hard overall 30-second wall-clock guarantee.

## 5. Diagnosis Trust Metrics

Correct means category AND original step match independently authored labels.
Partial means category correct but step wrong. Abstention is kept separate even
when it is the expected/correct control result. High confidence remains >= 0.80;
wrong step counts as confident-wrong. These are constructed tests, not user odds.

| Regression subset | Total | Expected positive failures | Correct diagnoses | Partial | Wrong | Abstained | High confidence | HC correct | HC wrong | Confident-wrong |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Packaged + two saved OSS cases | 16 | 8 | 8 | 0 | 0 | 8 | 8 | 8 | 0 | 0/8 (0%) |
| New offline trace probes | 14 | 3 | 3 | 0 | 0 | 11 | 3 | 3 | 0 | 0/3 (0%) |
| Hostile mocked remote response | 1 | 0 | 0 | 0 | 1 | 0 | 1 | 0 | 1 | 1/1 (100%) |
| All above regression probes | 31 | 11 | 11 | 0 | 1 | 19 | 12 | 11 | 1 | 1/12 (8.3%) |

This table does not count every historical unit-test subcase as a new accuracy
sample. The two saved OSS cases are engineered maintainer tests, not natural
failures. Mocked remote testing is separated because it is not model benchmarking.
`agentlens evaluate` currently runs the 16 JSON cases; the added 15 probes run in
pytest/unittest, including the failing remote case. Doctor does NOT cover these
additional trust probes and cannot certify release readiness.

**Internal natural failures:** total 0; correct 0; partial 0; wrong 0; abstained 0;
high confidence 0; HC correct 0; HC wrong 0; confident-wrong 0/0 (unmeasured).

**External developer failures:** total 0; correct 0; partial 0; wrong 0; abstained 0;
high confidence 0; HC correct 0; HC wrong 0; confident-wrong 0/0 (unmeasured).

The 12-case table test covers recovery, combined failures, partial/malformed
output, insufficient subtle routing evidence, overlapping successful tools,
unrelated warning, justified retry, dependency failure, and loop. Two additional
offline tests cover conflicting routing evidence and drift preceding wrong tool.
Before repair, recovery and conflicting routing were confident false positives.
No expected labels were changed after diagnosis; no difficult case was removed.

## 6. Live Provider Verification

**LIVE PROVIDER VERIFICATION: BLOCKED - KEY UNAVAILABLE**

| Provider | Normal | Tool + result | Streaming | Error | Responses | Async |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI/Python | BLOCKED | BLOCKED | BLOCKED | BLOCKED live; PASS local transport | BLOCKED | BLOCKED |
| Anthropic/Python | BLOCKED | BLOCKED | BLOCKED | BLOCKED live; PASS local transport | NOT SUPPORTED / not applicable | BLOCKED |
| OpenAI/Node | BLOCKED | BLOCKED | NOT SUPPORTED | BLOCKED live; PASS local fetch | NOT SUPPORTED | BLOCKED live |
| Anthropic/Node | BLOCKED | BLOCKED | NOT SUPPORTED | BLOCKED live; PASS local fetch | NOT SUPPORTED / not applicable | BLOCKED live |

Provider tests use Python OpenAI 2.41.0 / Anthropic 0.107.0; framework tests use
LangGraph 0.6.11. A supplied key must be fresh and configured securely. Do not
reuse credentials exposed in previously shared documents. Limit live testing
to small token budgets, one local harmless tool, and no actual customer action.

## 7. Real Agent Results

| Agent | Runs | Natural failures | Correct | Partial | Wrong | Abstained | Confident-wrong |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Research | 0 | 0 | 0 | 0 | 0 | 0 | Unmeasured |
| Customer support | 0 | 0 | 0 | 0 | 0 | 0 | Unmeasured |
| Data analysis | 0 | 0 | 0 | 0 | 0 | 0 | Unmeasured |
| Planning | 0 | 0 | 0 | 0 | 0 | 0 | Unmeasured |

Not built/run as genuine model agents in this audit: no provider access was
available. Two existing fake customer-support examples were run for capture/CLI
smoke testing only. They are not counted above. No synthetic failure was recast
as a naturally occurring failure to fill the requested table.

Next live protocol: keep real research search/fetch/summarize tools, read-only
support/account fixtures, local data/query/report tools, and planning/constraint
tools correct and clearly described. Vary legitimate user inputs; do not insert
broken routing or labeled causes. Use the existing decorator around the whole
workflow, checkpoint at meaningful boundaries, and record actual results.
On suspected failure, record the raw observation and independent expected
cause/step/fix BEFORE any command that shows diagnosis. Preserve both answers.

## 8. External Developer Results

Developers onboarded: 0. Independent failures: 0. Correct: 0. Partial: 0.
Wrong: 0. Abstained: 0. Confident-wrong: unmeasured. Useful diagnoses: 0.
Fixes confirmed useful: 0. Repeat users: 0. Payment signals: 0.

`feedback/users.csv` and `feedback/outreach.csv` have zero nonempty data rows.
No user reactions or ground truth were invented. Three independent developers
must test their own runs, with usefulness/resolution recorded separately from
category/step correctness. Repeated interactions are not additional users.

## 9. Support Contract

See [module12_support.md](module12_support.md). Supported, partial, manual and
unsupported scopes are explicit. Live visibility design is local-first and
deferred. The [OTel mapping](otel_compatibility.md) is a compatibility review only,
based on current developing conventions, not a dependency/exporter claim.

Module 1: offline supported calls, tool selection, explicit result requirements,
messages/schemas, usage, latency, local hierarchy, inspection, atomic storage and
privacy regressions pass. Live calls, unclosed/unsaved active-run durability and
universal completeness are not proven. Partial/malformed reads fail gracefully.

Module 2: narrow rules, abstention, repaired recovery/conflicts, original steps,
source labels, uncalibrated-score wording, suggested-fix status, feedback capture
and confident-wrong metrics exist. Model narrative grounding, confidence on
independent traces and actual usefulness remain open. Thus the checklist is not
fully satisfied even though the original JSON fixtures match.

## 10. Claims Corrected

- Evaluation no longer calls folder membership "real-world accuracy"; provenance
  groups and unclassified cases are printed separately. Legacy programmatic
  `real_world_*` keys remain for compatibility and refer to saved-case rows.
- Similarity now says "Suggested fix (unverified)", not "Fix used". Exact
  developer-reported attempted change/outcome is separate metadata.
- CLI diagnosis says root-cause step and suggested/unverified fix. Structural
  findings are labeled schema/explicit contradiction findings, not broad facts.
- README documents the unresolved remote validation limitation, explicit memory,
  replay controls, population metrics and precise support boundaries.
- No website visual design or website files were changed. Existing website copy
  already qualifies illustrative traces and conditional framework support.

## 11. Verification

| Check | Baseline | Final |
| --- | --- | --- |
| `python -m pytest -q` | 95 passed, 1 upstream warning | 107 passed, 1 failed, 1 upstream warning |
| `python -m unittest discover -s tests -v` | 95 passed | 108 run, 1 failure (same remote-causality probe) |
| Ruff on CLI/core/SDK/engine/server/tests | PASS | PASS |
| mypy, no incremental cache, CLI/core/SDK/engine | PASS, 23 files | PASS, 24 files |
| Source / isolated CLI doctor | Healthy | Healthy; limited local mechanics |
| Source / isolated evaluate | 16 category/step matches, 8 abstentions | Same; populations split |
| `npm ci` | PASS | PASS |
| `npm test` | 6 passed | 6 passed, Node 22.17.1 |
| TS build / consumer type checks / built import | PASS (npm test) | PASS (npm test) |
| Python wheel and sdist | PASS after network approval | PASS |
| Isolated editable `pip install -e . --no-deps` | Not needed for baseline source tests | PASS in temporary venv |
| Isolated wheel, no optional deps | PASS | PASS on Python 3.9.20 |
| Wheel import/doctor/demo/list/show/diagnose/anonymize/feedback/evaluate | PASS | PASS; 14 packaged cases outside checkout |
| Both provider examples | Not counted as live | PASS with fake/local clients, three spans each |
| Prior privacy + hostile diagnosis + remote transport regressions | PASS in full baseline | 34 passed in focused rerun |

Initial bare `agentlens doctor` failed evaluation and bare `agentlens evaluate`
reported zero fixtures. Cause: PATH selected an old Python 3.13 CLI under
`/Library/Frameworks/Python.framework/Versions/3.13/bin`, while source tests use
Python 3.9.20 in micromamba. This is an onboarding environment hazard, not a
failure of the current wheel. The temporary venv CLI works; the global install
was not modified. README already instructs use of an activated environment.

Initial isolated build could not resolve the package index inside the sandbox;
it passed after the explicit network approval. No publish command was run.
Python 3.10/3.11/3.12 and Node 20 were not re-executed locally in this audit;
the existing CI matrix is configuration, not new evidence of hosted CI success.
The LangChain serializer deprecation warning is upstream and does not fail tests.

## 12. Files Changed

- `agentlens.py`: recorded replay navigation/full detail/state comparison,
  honest root-step/fix/structural labels, blind feedback fields, similarity wording.
- `agentlens_core/state.py`: pure nested JSON-state comparison and bounded display.
- `agentlens_sdk/streams.py`: EOF without provider completion is partial, not completed.
- `agentlens_engine/classifier.py`: refuse conflicting routing destinations and
  stop treating a historical error followed by model response as terminal proof.
- `agentlens_engine/diagnose.py`: new suggestions explicitly `fix_status=unverified`.
- `agentlens_engine/hallucination.py`: apply schemas in recorded order, not retroactively.
- `agentlens_engine/similarity.py`: distinguish new suggestion from exact manual fix outcome.
- `agentlens_engine/evaluate.py`: separate provenance populations and outcome denominators.
- `tests/test_module12_beta.py`: nine focused implementation/contract tests.
- `tests/test_module12_trust.py`: 12 table-driven offline cases, precedence/conflict
  probes and the deliberately still-failing remote acceptance regression.
- `feedback/users.csv`: append independent ground truth and outcome columns; no user rows added.
- `real_world_cases/CASE_TEMPLATE.md`: blind review protocol, provenance and fix-outcome metadata.
- `real_world_cases/langgraph_tool_selection/expected_diagnosis.json` and
  `real_world_cases/crewai_tool_selection/expected_diagnosis.json`: label existing
  maintainer-operated cases as regression only; expected diagnoses unchanged.
- `README.md`: narrow behavior/support/remaining-blocker documentation.
- `docs/module12_support.md`: capability matrices, manual boundaries, deferred active-write design.
- `docs/otel_compatibility.md`: tentative mapping, development status and privacy boundaries.
- `docs/module12_beta_report.md`: this report.

## 13. Git State

Staged: **false**. Committed: **false**. Pushed: **false**. Published: **false**.
Deployed: **false**. HEAD remains the baseline commit. Existing branch retained.
No unrelated user edits existed at the start or were overwritten.

`codex.md`, `.agentlens/`, `.env`, generated run JSON, anonymized JSON, cache files
and egg-info remain ignored and unstaged. `codex.md` was not changed. Test run
artifacts were created in temporary directories; build metadata is ignored.

## 14. Remaining Risks

**BETA BLOCKERS:** semantic grounding of remote cause/fix; full test suite has
one real failure; no real-provider matrix; no independent developer validation.

**SHOULD FIX SOON:** active-run evidence durability; historical-versus-terminal
status; calibration and useful abstention on natural failures; temporal schema
association for more complex/interleaved workflows; show raw supporting evidence
and source consistently in every inspector; broad/inaccurate prose could still
be accepted when a narrow quote happens to exist. Raw/export privacy remains
best effort, not an assertion that all PII or encoded credentials are removed.

**DEFERRED ROADMAP:** universal frameworks, full Node parity, automatic memory,
distributed tracing, rerunning/fix execution, hosted streaming, all Modules 3-8
expansion, dashboards/auth/billing, test-generation platform and OTel exporter.

## 15. Final Verdict

**MODULES 1 + 2 VERDICT: NOT YET BETA COMPLETE**

Minimum next work: repair or explicitly remove remote narrative diagnosis from
the trusted beta scope; keep the failing regression until the actual acceptance
defect is resolved. Run a small real-provider matrix with fresh environment keys.
Then validate actual correctly-built agents and onboard three independent
developers with blind expected causes and usefulness/resolution feedback.
Do not add more platform scope to disguise these missing trust measurements.

## 16. Remote Evidence Validation Repair (September 17, 2026)

### Original Bug and Reproduction

The unchanged `BetaTrustTests.test_remote_quote_is_not_enough_to_establish_causality`
in `tests/test_module12_trust.py:50` was run alone before editing. It failed:
expected `unknown`, actual `loop`. The trace is a successful run with one tool
span: `lookup`, input `{"id":"C17"}`, output `{"record":"found"}`. There is no
second call, retry budget, terminal error or failed execution.

The mocked provider returned:

```json
{
  "root_cause_category": "loop",
  "confidence": 0.99,
  "failed_at_step": 1,
  "failed_at_tool": "lookup",
  "explanation": "The agent looped forever because the model ignored a retry budget.",
  "fix": "Delete lookup and switch providers.",
  "secondary_issues": [],
  "evidence": [{"step": 1, "field": "output", "quote": "found"}]
}
```

`found` really occurs in step 1's output. It proves neither a loop nor the
invented ignored budget nor the need to switch providers. The old pipeline
parsed JSON, validated field types/category/step/tool and located the quote,
then accepted the entire explanation/fix. It never called the category rules
for remote acceptance. This was not a missing quote check.

### Root Cause and Repair

- `agentlens_engine/classifier.py:47`, `validate_diagnosis`: schema and citation
  location validator only. Its docstring now explicitly says this is NOT causal
  validation. Existing syntax-validation tests retain that limited contract.
- `agentlens_engine/diagnose.py:54`, `_supported_diagnosis`: uses the existing
  `classify_from_evidence` and `generate_fix`, including candidate precedence.
  No second set of six category detectors was introduced.
- `agentlens_engine/diagnose.py:61`, `_verify_remote_diagnosis`: independently
  recomputes the supported candidate, validates citations against the redacted
  trace, and requires matching category, originating step/tool, explanation,
  fix, secondary categories and complete evidence. Confidence cannot exceed the
  local evidence score. Extra provider fields are discarded, not merged.
- `agentlens_engine/diagnose.py:84`, `_diagnose_with_llm`: sends redacted trace
  plus a supported candidate and explicitly requests the restricted contract.
  Both provider paths check the proposal before return, with at most one retry.
- `agentlens_engine/diagnose.py:24`, `diagnose_run`: rechecks at the acceptance
  boundary, so an adapter/test double cannot bypass the gate. Invalid proposals
  use the existing heuristic fallback with `remote_warning`; insufficient local
  evidence returns unknown/zero confidence. No replacement cause is invented.

The model is permitted to propose only the already-supported candidate and may
lower confidence. It cannot add causal prose. This deliberately rejects even
correct natural-language paraphrases. It is a template/structural contract, NOT
a semantic theorem prover, independent model corroboration, or expanded RCA
coverage. `diagnosis_source=llm` means the returned proposal passed that contract;
the displayed facts/fix are locally reconstructed, not arbitrary model prose.
All generated fixes remain `fix_status=unverified`.

### Validation Model

| Requirement | Enforcement |
| --- | --- |
| Evidence existence | Quoted content must occur in the cited field |
| Evidence location | Original step must exist; tool and field must belong there |
| Category consistency | Existing detector must establish that category; generic tool errors, repeated names and long traces alone are insufficient |
| Causal relationship | Only detector-supported facts/templates can be returned; added English claims reject the proposal |
| Root-cause step | Must match the earliest supported candidate, not a downstream symptom; original indices retained |
| Downstream consequence | Cascade reuses the existing ordered same-field/value/digest checks and corresponding downstream field error, including recovery guards |

Redaction is a representation boundary, not causal proof. For example, the
privacy policy redacts the `email` field even when its value is null. The gate
compares the proposal to the redacted candidate the provider saw, but derives
the null-value propagation relationship from the original local trace. It does
not infer equality/causation merely because two redacted values look alike.

### Adversarial Results

`tests/test_remote_evidence.py` records the A-H traces and expected outcomes
before calling diagnosis. Each A-H response passes the old quote/location
validator, isolating the additional acceptance gate under test.

| Case | Expected | Actual | Result |
| --- | --- | --- | --- |
| A: customer_not_found / unrelated card decline | Reject fabricated cascade; abstain | unknown, step 0, heuristic | PASS |
| B: actual null propagation attributed downstream | Reject wrong origin; trusted fallback | cascade, step 1, heuristic | PASS |
| C: null email actually passed to failing send_email | Accept supported cascade | cascade, step 1, llm | PASS |
| D: timeout history followed by successful retry/final answer | Reject historical loop | unknown, step 0, heuristic | PASS |
| E: wrong-tool error explicitly names declared alternative | Accept mismatch | tool_selection, step 2, llm | PASS |
| F: genuine quotes connected in reversed execution order | Reject invented dataflow | unknown, step 0, heuristic | PASS |
| G: identical failed calls plus terminal iteration limit | Accept no-progress loop | loop, step 1, llm | PASS |
| H: retry with changed input | Do not infer loop from repeated name | unknown, step 0, heuristic | PASS |

The original healthy-lookup/`found` regression now passes without any change to
its trace, mocked output, expectations, skip status or source file.

Twelve manipulations of the valid cascade are rejected: fabricated explanation,
partially valid explanation with an invented claim, unsupported destructive fix,
free-form paraphrase, wrong step, wrong category, nonexistent step, malformed
evidence, irrelevant real quote, omitted downstream consumption, invented
secondary category and inflated confidence. The trusted fallback preserves the
supported cause/fix and does not expose the rejected prose.

Additional tests cover all six categories under the shared acceptance contract,
earlier-cause precedence, redacted citations, original indices 17/31, lowered
confidence with an uncertainty message, discarded invented metadata and fake
`fix_status=verified`. Mocked OpenAI AND Anthropic adapters reject a fabricated
extension then accept the supported proposal on their second/last attempt.
These are local protocol tests, not live model quality measurements.

Two old source/transport tests explicitly expected quote-only proposals to be
accepted. Their original weak payloads are retained as rejection tests in
`tests/test_beta_safety.py` and `tests/test_remote_opt_in.py`; their expectations
now enforce the changed safety contract. Positive acceptance is tested separately
with real structural mismatch/cascade/loop evidence. The original failing trust
regression and all independently authored corpus labels are unchanged.

### Verification Results

| Check | Repair result |
| --- | --- |
| Full pytest | 113 passed; one upstream LangChain pending-deprecation warning |
| Full unittest discovery | 113 tests, OK |
| Ruff | PASS |
| mypy | PASS, 24 source files |
| Doctor, temporary source-linked environment | Healthy; all six checks PASS |
| Evaluate | 16/16 category AND original-step matches, 8 diagnoses/8 abstentions, 0 errors, 0 false positives/negatives, 0/8 confident-wrong |
| Focused prior hostile tests | 53 passed |
| Evaluation expectations/denominators and CLI token/index tests | 14 passed |
| npm ci | PASS, clean dependency install |
| TypeScript build/consumer checks/Node tests | PASS in a fresh temporary copy with the same sources/lockfile: all 6 Node tests; checkout attempts timed out during imports (see below) |
| Wheel and sdist | PASS; wheel built from sdist with isolated build dependencies |
| Fresh non-editable wheel smoke | PASS on Python 3.9.20, no optional dependencies: import, doctor, demo, list/show, diagnose, runs replay, anonymize, feedback, evaluate; 14 packaged cases |

The new remote adversarial cases run in the Python suite, not `agentlens evaluate`.
Do not convert those manipulated responses into additional independent accuracy
samples. Both saved LangGraph/CrewAI cases still pass as engineered regressions;
external-developer accuracy is still unmeasured.

The isolated build initially failed due to sandbox DNS/index access and succeeded
after explicit network approval. Nothing was published. Artifacts are in
`/tmp/agentlens-remote-evidence-final-dist/`. `tests/artifact_smoke.py` now also tests
replay next/full/back/quit from the installed wheel outside the repository.
No optional provider dependencies or keys are required for that smoke test.

The first added replay smoke invocation incorrectly used `agentlens replay` and
failed with CLI exit 2. The harness was corrected to the existing command,
`agentlens runs replay`; no product CLI change was necessary. Wheel and sdist were
rebuilt after the correction and the final wheel passed a fresh installation.
Both archives exclude private files; the sdist includes the corrected smoke test.

`npm test` in the Desktop checkout timed out three times at the test-file level,
before any of the six subtests began, including an approved unsandboxed attempt.
Direct import tracing showed slow progress through the provider SDK module tree;
the OpenAI import eventually completed. No network/provider request was made.
The same source, tests, package manifest, lockfile and tsconfig were copied to
`/tmp/agentlens-node-verification.31m5Li`, followed by `npm ci` and `npm test`.
That clean install passed build, consumer types and all six tests (187 ms test
runner duration). No timeout was raised and no Node code/dependency was changed.
This isolates the observed failure to the checkout/install environment, but does
not identify its underlying filesystem/import-latency cause. Keep it as a local
environment caveat, not a claim that all checkout executions were green.

Every requested previous hostile regression is retained: AWS key/session-token
redaction, expired-session recovery, business-text `invalid` not implying cascade,
temporal schemas, conflicting routing, recovered drift, incomplete streams,
original steps, token aliases/deduplication, malformed expectations and denominator
accounting. No failing expectation was removed to inflate evaluation scores.

### Current Blockers and Limits

1. Live-provider verification remains unperformed; credentials were unavailable
   in the prior audit. No live-provider work was attempted in this repair.
2. Independent external developer validation remains zero. Usefulness, trust,
   repeat use and calibration on natural failures remain unknown.

The narrow local predicates can still miss subtle failures. Exact template
matching intentionally sacrifices free-form model explanations for fail-closed
acceptance. Scores are not calibrated probabilities, fixes are suggestions, and
rule matches are not proof of real-world truth. Existing capture durability and
best-effort privacy limitations in the support contract are unchanged.
No Modules 3-8 work, onboarding, UI, backend or architecture expansion occurred.

### Repair Git State

All pre-existing uncommitted repairs were preserved. This repair adds a gate and
prompt contract in `diagnose.py`/`classifier.py`, five adversarial test methods in
`tests/test_remote_evidence.py`, adjusts the two obsolete acceptance tests, adds
wheel replay smoke coverage, and updates README/support/report documentation.

Modified tracked files: 15. Untracked files: 7 (including prior audit artifacts).
Staged: none. New commits: none. Pushed: no. Published: no. Deployed: no.
HEAD remains `59ce36159f09dd059d13dc7b0b4bba1ec87f840f`.
`codex.md` was not modified. Private data, generated runs, caches and egg-info are
ignored and not tracked/staged. Build/test output is local only.

### Current Verdict

REMOTE EVIDENCE VALIDATION: PASS (restricted structural/template contract)

MODULES 1 + 2: NOT YET BETA COMPLETE

## 17. Pre-PR Classification and Separate Readiness Gates

Reviewed September 17, 2026. This is a diff classification and verification pass,
not another architecture audit. No new classifier, SDK, CLI, UI or backend changes
were made in this pass. The prior 22 changed/untracked files were inspected before
staging; the stale live-validation document is the only additional file.

| File | Why changed | Keep? |
| --- | --- | --- |
| `README.md` | Document existing repair behavior, limits and evidence labels | YES |
| `agentlens.py` | Existing replay/state inspection and honest source/fix/feedback labels | YES |
| `agentlens_core/state.py` | Existing recorded-state comparison, not live instrumentation | YES |
| `agentlens_engine/classifier.py` | Recovered-error/conflicting-route guards and remote contract | YES |
| `agentlens_engine/diagnose.py` | Structural remote acceptance, safe fallback and unverified fix status | YES |
| `agentlens_engine/evaluate.py` | Separate regression/user populations and honest denominators | YES |
| `agentlens_engine/hallucination.py` | Apply tool schemas in recorded order | YES |
| `agentlens_engine/similarity.py` | Separate suggested fix from developer-reported outcome | YES |
| `agentlens_sdk/streams.py` | EOF without provider completion remains partial | YES |
| `tests/artifact_smoke.py` | Exercise installed-wheel replay outside checkout | YES |
| `tests/test_beta_safety.py` | Reject obsolete quote-only acceptance case | YES |
| `tests/test_remote_opt_in.py` | Preserve transport/privacy checks under stricter acceptance | YES |
| `tests/test_module12_beta.py` | Existing state/schema/stream/hierarchy/metric regressions | YES |
| `tests/test_module12_trust.py` | Original hostile regression, recovery/conflict/precedence tests | YES |
| `tests/test_remote_evidence.py` | Existing A-H adversarial and provider-adapter regressions | YES |
| `docs/module12_beta_report.md` | Historical audit evidence, repair results and this classification | YES |
| `docs/module12_support.md` | Supported scope and separate engineering/product gates | YES |
| `docs/otel_compatibility.md` | Prior compatibility review only; no exporter/dependency added | YES |
| `feedback/users.csv` | Header-only manual feedback fields; zero developer records | YES |
| `real_world_cases/CASE_TEMPLATE.md` | Blind ground truth and debugging-time usefulness protocol | YES |
| `real_world_cases/crewai_tool_selection/expected_diagnosis.json` | Label maintainer example as regression; ground truth unchanged | YES |
| `real_world_cases/langgraph_tool_selection/expected_diagnosis.json` | Label maintainer example as regression; ground truth unchanged | YES |
| `docs/live_provider_validation.md` | Refresh stale blocked status and requested real-provider matrix | YES, documentation only |

No raw/provider outputs, temporary traces, anonymized exports, cache files,
egg-info, screenshots, local debug scripts, `codex.md`, `.env` or website files
belong in this commit. The credential-pattern scan of the 22 initial paths found
only two references to a pre-existing fake key in the doctor anonymization test;
manual inspection confirmed both are synthetic test constants, not new secrets.
Pattern scanning is not a guarantee against every secret format.

### Live Validation Gate

Presence-only environment check: `OPENAI_API_KEY=false`,
`ANTHROPIC_API_KEY=false`. No credential value was displayed or copied. No real
provider call was made, so the requested matrix and actual-key-in-trace checks
remain BLOCKED/NOT TESTED, not PASS. See `live_provider_validation.md`.

### Readiness Language

**Engineering:** the identified code blocker is repaired and offline verification
passes; technical readiness for limited external beta awaits live-provider checks.
Do not count missing developers as missing implementation.

**Product:** zero independent developers, zero user-confirmed usefulness results
and no measured real-world accuracy. After live validation, recruit three
developers and compare AgentLens with how they would otherwise debug the failure.
No additional internal fixture campaign or product expansion is planned.

### Pre-Commit Verification

Final verification for the reviewed snapshot:

- `python -m pytest -q`: 113 passed, one upstream LangChain warning.
- Ruff: PASS. mypy: PASS, 24 source files.
- Source doctor: healthy. Evaluate: 16/16 category and original-step matches,
  including both saved OSS regressions; confident-wrong 0/8 scored positives.
- `npm ci` and `npm test` in the identical temporary package copy: PASS,
  TypeScript build, consumer declarations and all 6 Node tests. The earlier
  Desktop import-timeout caveat in section 16 remains documented.
- Rebuilt wheel/sdist: PASS. A fresh non-editable wheel install outside the
  checkout passes import, doctor, demo, list/show, diagnose, runs replay,
  anonymization, feedback and evaluation (14 packaged cases, no optional deps).
- Whitespace check and ignore/tracked-path checks: PASS. No private/generated
  files are included. The public README PR was already merged; the repair branch
  starts at `origin/main` (`f2bada4`) rather than including an unrelated website PR.

No live result is inferred from mock transports or the engineered OSS cases.
This change is a reviewable engineering-safety PR, not a beta release or a claim
of real-user accuracy. There are no additional product implementation changes in
this final classification pass.

## Live OpenAI Provider Validation — Earlier Blocked Attempt

Date: September 17, 2026.

Preflight: BLOCKED. The presence-only check in the command execution environment
returned `OPENAI_API_KEY available: False`. A key exported in another terminal
is not evidence that this execution environment can access it. No credential was
read from conversation history, copied, printed, persisted or modified.

Branch: `codex/module12-beta-safety`.
Commit: `33d219d8eab0b75c0678a744993ddd976c864575`.
Working tree before this report update: clean.
Models: none; no API requests were attempted.

| Check | Result |
| --- | --- |
| Basic request | NOT TESTED: credential unavailable |
| Responses API | NOT TESTED: credential unavailable; not a claim of unsupported integration |
| Tool selection | NOT TESTED |
| Tool result / automatic versus manual capture | NOT TESTED |
| Async | NOT TESTED |
| Streaming | NOT TESTED |
| Interrupted stream | NOT TESTED |
| Error handling | NOT TESTED |
| Token capture | NOT TESTED |
| Latency capture | NOT TESTED |
| Trace persistence | NOT TESTED |
| Credential leakage | NOT TESTED: full-key comparison requires the environment credential |
| Diagnosis of live traces | NOT TESTED: no live trace generated |

API calls made: 0. API cost for this attempt: $0.
No live traces, exports, logs or validation scripts were generated. This report
contains only preflight metadata and blocked results. No credential-leak PASS or
NOT FOUND result is claimed without an actual comparison against the key.

Regressions were not rerun because the live-validation stage could not start and
no product code changed. Section 17 records the previous offline results; those
are not new live-provider evidence.

OPENAI LIVE VALIDATION: FAIL (preflight blocked, not an observed product failure).
ANTHROPIC LIVE VALIDATION: UNVERIFIED; no Anthropic request attempted.
MODULE 1 TECHNICAL READINESS: NOT READY for live-validated beta sign-off.
MODULE 2 TECHNICAL READINESS: NOT READY for live-validated beta sign-off.
These readiness labels reflect the unverified live gate, not a new code defect.
EXTERNAL USER VALIDATION: 0 developers.

Next action: make the credential available to the process executing validation,
then repeat the presence-only check before any live request. Do not paste the
credential into chat, a command submitted here, repository files or the report.
Only this report was edited; no commit, push, publication, deployment or PR was
performed for this attempt.

## Live OpenAI Provider Validation

Date: September 17, 2026. This authenticated attempt supersedes the earlier
blocked attempt preserved above. Presence-only preflight: `OPENAI_API_KEY available: True`.
Branch: `codex/module12-beta-safety`; commit:
`33d219d8eab0b75c0678a744993ddd976c864575`.
Initial working tree: only `docs/module12_beta_report.md` modified, unstaged.
Those prior report edits were preserved. No product code or test expectations changed.

### Provider and request controls

Real OpenAI SDK 2.41.0, explicit `https://api.openai.com/v1` endpoint,
`max_retries=0`, 30-second inference timeout. A real model-list request confirmed
project access to `gpt-5.4-nano`; completed responses identified
`gpt-5.4-nano-2026-03-17`. Current model capabilities and pricing were checked in
[official OpenAI documentation](https://developers.openai.com/api/docs/models/gpt-5.4-nano).
Reasoning was disabled; each successful request allowed at most 64 output tokens.
Only synthetic prompts and a harmless local weather function were used.

Eight real inference requests: six completed requests, one intentionally
interrupted stream, and one intentional invalid-model request. The tool workflow
uses two of the six completed requests. HTTP observation recorded seven 200
responses and one 404 from the real endpoint, with request-ID presence verified
without copying header values into the report. One additional successful model-list
request makes **9 requests that reached OpenAI**. An earlier model-list attempt
failed at sandbox connectivity before the approved network retry. No inference
was retried. No authentication-failure test or Anthropic request was made.

### Results

| Check | Result |
| --- | --- |
| Basic request | PASS |
| Responses API | PASS |
| Tool selection | PASS |
| Tool result | PASS — AUTOMATIC from the subsequent request |
| Async | PASS |
| Streaming | PASS |
| Interrupted stream | PASS |
| Error handling | PASS |
| Token capture | PASS when provider usage was received |
| Latency | PASS |
| Trace persistence | PASS |
| Credential leakage | PASS |
| Diagnosis | PASS — honest offline abstention on the real 404 run |

Each row below was read from its saved JSON using the canonical trace reader;
all span IDs were unique. Exports were prepared locally for all seven runs.

| Case | Run ID | Saved status | LLM spans | Readable / exported |
| --- | --- | --- | --- | --- |
| basic | `ab37429d-affb-4944-a8c8-49570621f95b` | success | 1 | PASS |
| responses | `2f0a1970-bf7e-4d89-84c6-beab39d3bb9a` | success | 1 | PASS |
| tool | `cf71852c-1cbd-417b-aeef-e2035d9e19f9` | success | 2 | PASS |
| async | `9bd62899-15eb-4ed3-84ef-03acec134888` | success | 1 | PASS |
| streaming | `2dd5f647-0255-4a95-8ab1-ec4b04aefd58` | success | 1 | PASS |
| interrupted | `55d3a717-0d60-4293-8eab-00ecf89b2e21` | partial | 1 | PASS |
| error | `059777d2-bec2-4d11-824f-b3e4f3c35f44` | error | 1 | PASS |

Basic request individual checks: real endpoint PASS; real response PASS; run
creation PASS; LLM span PASS; provider PASS; model PASS; input PASS; output PASS;
latency PASS; supplied token usage PASS; run status PASS; saved trace PASS.
The returned and captured content was exactly `LIVE_OK`.

Responses API individual checks: request capture PASS; response capture PASS;
model PASS; input PASS; output PASS; usage PASS; latency PASS; run status PASS;
saved trace PASS. The response text was exactly `LIVE_OK`.

Tool workflow individual checks: schema PASS; model selection PASS; name PASS;
arguments PASS; tool result PASS; subsequent response PASS; complete run PASS.
The model selected `get_weather` under automatic tool choice and supplied
`city=Chicago`. The local function returned synthetic temperature 72 and sunny
conditions; the final response reflected those values. One tool span was
completed when AgentLens inspected the tool-result message in the next real
request. The validation workflow never called `record_tool_result()`.
This is automatic result capture at the next-request boundary, not automatic
local tool execution or tool-runtime measurement; standalone final results still
have the documented manual-recording boundary.

Async individual checks: run starts PASS; correct run membership PASS; span PASS;
response PASS; usage PASS; latency PASS; coroutine creation does not save PASS;
no saved trace before coroutine return PASS; persistence after execution PASS;
final status PASS. The existing async run decorator was used.

Streaming individual checks: starts PASS; chunk handling PASS; reconstructed
`LIVE_OK` PASS; exactly one LLM span/no duplicates PASS; supplied usage PASS;
latency PASS; final success status PASS; readable trace PASS. Five chunks were
consumed. Interrupted-stream individual checks: first chunk consumed PASS;
stopped before finish event PASS; explicit close inside the run PASS; span and
run both `partial` PASS. No final usage arrived before interruption; absent usage
was retained rather than invented. This does not validate abandoned/unclosed
streams or hard process death.

Safe error individual checks: expected SDK `NotFoundError`/404 PASS; no unexpected
crash PASS; LLM error and error events captured PASS; error run status PASS;
readable trace PASS; credentials absent PASS. There was one failed API request;
multiple error events reflect SDK-call and enclosing-run capture, not retries.
No response output or usage was supplied for this failed request.

RCA trace inspection: model calls, synthetic inputs, outputs, applicable tool
schema/selection/arguments/result, failure evidence, latency, provider-supplied
usage, and run status were present. Observed LLM latencies ranged from about
569 to 3010 ms, including the interrupted and failed requests.

### Diagnosis and evidence boundary

The current checkout CLI was invoked as `python agentlens.py diagnose <run_id>`
on the genuine invalid-model run only, with no remote-provider flag. It executed
successfully and returned `unknown`, step 0 (abstention sentinel), confidence 0,
source `heuristic`, and insufficient-evidence wording. The actual failed LLM
call is step 1; no positive causal category or root-cause step was asserted.
Claimed-step and positive-causal-relationship checks are therefore NOT APPLICABLE,
not a claim that a causal explanation was proven. Evidence validation returned
no errors. An offline proposal-rejection probe against this unchanged real trace
rejected an added unsupported loop explanation. It was not a live remote-model
response. No healthy run was relabeled or diagnosed as a fabricated failure.
The earlier remote-evidence regressions also passed in the full Python suite.

### Credential checks

The actual environment credential was compared internally against raw traces,
logs, all seven locally prepared exports, reports, validation scripts, generated
caches/build artifacts, and the isolated Node verification tree. No credential
value or fragment was printed or written by the validation workflow.

RAW TRACE KEY CHECK: NOT FOUND

LOG KEY CHECK: NOT FOUND

EXPORT KEY CHECK: NOT FOUND

REPORT KEY CHECK: NOT FOUND

TEMP ARTIFACT KEY CHECK: NOT FOUND

Obvious authentication-header persistence: NOT FOUND in live raw traces.
All live artifacts remain under ignored `.agentlens/`; the isolated Node tree
is outside the repository. Nothing was staged or published.

### Regression verification and environment caveats

- Full Python suite: 113 passed; one upstream LangChain pending-deprecation warning.
- Ruff: PASS using CI paths.
- mypy: PASS, 24 source files using CI paths.
- Current checkout doctor: PASS, all six checks.
- Current checkout evaluate: PASS, 16/16 category and original-step matches,
  8 diagnoses/8 abstentions, zero errors/false positives/false negatives,
  zero confident-wrong out of eight high-confidence diagnoses.
- The globally installed `agentlens` entry point resolves to a different Python
  installation: its doctor reported no fixture cases and its evaluate counted
  zero cases, despite exit status 0. These are not passing checks. Running
  `python agentlens.py doctor` and `python agentlens.py evaluate` against this
  checkout produced the valid passing results above. No global install changed.
- Checkout `npm test`: TypeScript build and consumer checking passed, then the
  test-file runner timed out after 30 seconds before its six subtests ran.
  One fresh temporary copy with byte-identical source/tests/manifests/lockfile
  passed offline `npm ci`, TypeScript build, consumer checks, and all six Node
  tests (about 215 ms runner time). The checkout timeout remains an environment
  caveat; no dependency version, source, or timeout was changed.

Regression children ran without provider credentials. Mocked-provider regressions
are offline evidence only and are not counted as live API requests.

### Usage and verdict

Observed supplied usage: 270 input tokens and 46 output tokens across the six
completed requests. At documented standard rates of $0.20/M input and $1.25/M
output tokens (zero cached input observed), their estimated cost is $0.0001115.
The interrupted stream supplied no usage, so the total billed cost cannot be
determined from these traces; this estimate excludes its unreported usage.
No exact-billing claim is made.

OPENAI LIVE VALIDATION: PASS within the tested Python OpenAI capture scope.

ANTHROPIC LIVE VALIDATION: UNVERIFIED.

MODULE 1 TECHNICAL READINESS: NOT READY for full multi-provider sign-off;
OpenAI live validation now passes, but Anthropic live coverage remains unverified.

MODULE 2 TECHNICAL READINESS: NOT READY for full multi-provider sign-off;
offline evidence validation and live-error abstention pass, but this attempt does
not establish live remote-model diagnosis or Anthropic behavior.

EXTERNAL USER VALIDATION: 0 DEVELOPERS.

Only this report changed among tracked files; its pre-existing edits remain.
Staged: none. Committed: no. Pushed: no. Published: no. Deployed: no.
The passing OpenAI result does not remove the documented capture limits or
establish independent developer accuracy/usefulness.

### Follow-up terminal attempt: authentication rejection

Reviewed September 17, 2026 (America/Chicago). The user subsequently ran the
private terminal harness. Its session timestamp is September 18, 2026 at
02:14:49 UTC, or September 17 at 21:14:49 America/Chicago.

This is a separate attempt from the successful `gpt-5.4-nano` matrix above.
Do not merge their request counts, credentials, models or conclusions. The
earlier saved results and inspection record corroborate that separate matrix;
they do not make this later request successful.

| Check | Follow-up result |
| --- | --- |
| Model requested | `gpt-4.1-mini`; no inference completed |
| Basic request | FAIL: HTTP 401, provider error code `invalid_api_key` |
| Requests attempted / HTTP responses | 1 / 1; stopped without retries |
| Responses, tools/results, async, complete/partial streams | NOT TESTED after authentication rejection |
| Intentional invalid-model test | NOT TESTED |
| Automatic error capture | PASS: error run, one LLM span and two error events |
| Trace metadata | Run grouping, provider, requested model, input, timestamps, latency and unique span IDs passed |
| Output / tokens | No successful model output or usage; successful capture remains untested in this attempt |
| Local diagnosis / CLI | PASS: abstained rather than inventing a supported causal category |
| Credential privacy | STRICT GATE NOT PASSED: masked credential hint persisted in the raw provider error |

The basic test's expected-success status check failed because the provider
rejected authentication. The saved `error` status was appropriate. This is not
evidence of a success-status capture bug or insufficient account quota. The
available evidence does not establish why the credential was rejected.

#### Privacy finding and audit limitation

The harness reported `NOT FOUND` for its in-memory full-key comparison, contiguous
12-character fragments and the last eight characters, and checked credential
field names. However, a subsequent content inspection detected the provider's
masked credential hint inside saved error text. No hint, fragment or raw error
was displayed or copied into this report.

Therefore `NOT FOUND` is only the result of those specific comparisons, not a
PASS for the stricter no-credential-fragments requirement. A masked provider echo
can evade those length-based checks and credential-field scanning when stored
under `error`. Treat this as a privacy finding; do not share the raw error trace.
No usable full-key disclosure is established by this review. The reviewer did
not have the environment credential and did not independently rerun the full-key
comparison. No product code was changed to conceal or fix this finding.

#### Follow-up regressions and verdict

The terminal harness saved exit-code-zero results for all five checks:

- Python: 113 tests passed.
- Ruff: all checks passed.
- mypy: no issues in 24 source files.
- Checkout doctor: healthy.
- Checkout evaluate: fixture accuracy 100%, 8/16 abstentions and 0/8
  confident-wrong scored high-confidence diagnoses. These are offline results,
  not real-user accuracy.

OPENAI LIVE VALIDATION FOR THIS ATTEMPT: FAIL/BLOCKED by authentication; remaining
live matrix not run. The harness's aggregate `PARTIAL` label describes completed
local checks, not successful authenticated inference.
PRIVACY VERDICT FOR THIS ATTEMPT: strict no-fragments requirement not satisfied.
ANTHROPIC LIVE VALIDATION: UNVERIFIED. EXTERNAL USER VALIDATION: 0 developers.
Billing cost is not determinable from this rejected request's trace; no usage
was returned. No further API requests were made during review.

The earlier successful OpenAI matrix remains historical evidence. This follow-up
does not grant a broader beta-readiness sign-off. Authentication needs resolving,
and the raw-error privacy boundary needs an explicit decision before sharing
these artifacts. Generated artifacts and the harness remain ignored. Only this
report was edited during review; no product edits, commits, pushes or publication.

## Authentication Error Privacy Repair (September 18, 2026)

This section records an offline code repair, not another provider-validation
attempt. All credentials in the new tests are synthetic. OpenAI API calls: 0.
Anthropic API calls: 0. No network requests, credential access, credential
rotation or dependency installation were needed.

### Reproduction and capture path

The initial synthetic suite reproduced seven failing tests before the repair.
Provider exceptions pass through `_capture_sync` / `_capture_async` and the
stream completion callback into `_begin_call.finish`. The exception text was
copied into the LLM span, `capture_error` events and the enclosing sync/async
`run` decorator's top-level error. `save_run` then passed the unsanitized run to
`atomic_write`, including its temporary file. Export-time anonymization was too
late to protect the raw trace, and its token pattern could redact only the first
part of a masked value while leaving the suffix behind.

The Node SDK had equivalent direct exception-string copies in its provider
callback and enclosing run, plus filesystem exception text in warnings.

### Repair and boundaries

- `agentlens_core/privacy.py`: reuse one recursive redaction policy for capture,
  anonymization and residual detection. Add masked/split/ellipsis credential
  forms, labeled hints, hint fields and complete authentication-header handling.
  Credential-only capture does not invoke optional NLP or scrub unrelated PII.
  Harmless serialized JSON keeps its original spacing. Redaction is idempotent
  on the covered cases and preserves token-count fields.
- `agentlens_sdk/collector.py`: sanitize spans when appended, tool results when
  updated, the top-level error and the entire snapshot before atomic persistence.
  Known authentication/authorization exceptions omit opaque provider text rather
  than relying on recognizing every possible hint. Preserve provider, model,
  numeric HTTP status, error type, safe request-ID metadata and known error code.
- `agentlens_core/trace.py`: sanitize legacy/external traces on normalization, so
  CLI inspection and local/remote diagnosis preparation do not re-expose known
  credential patterns. This does not rewrite the historical source files.
- `agentlens_sdk_ts/src/index.ts`: omit authentication and credential-bearing
  exception messages conservatively instead of adding a separate partial-masking
  implementation. Preserve safe HTTP/type/request-ID metadata. Filesystem warnings
  no longer echo exception payloads. Ordinary non-sensitive errors remain readable.
- Regression coverage is in `tests/test_auth_error_privacy.py` and
  `agentlens_sdk_ts/tests/package.cjs`; no existing assertions were weakened.

| Boundary | Evidence |
| --- | --- |
| Raw saved JSON | PASS: actual SDK/decorator persistence, manual snapshots and nested error/context fields |
| In-memory error spans | PASS: credentials removed before save |
| Sync/async/stream exception paths | PASS: synthetic failures and local SDK transports |
| Authentication metadata | PASS: HTTP status, exception type and safe request ID retained |
| `runs show` | PASS: captured stdout/stderr contain no tested sensitive fragments |
| Anonymized JSON | PASS: saved output checked, not just terminal rendering |
| Upload preparation | PASS: local exported JSON checked; nothing uploaded |
| Diagnosis input | PASS: normalized/preprocessed input and intercepted remote adapter input checked without a remote call |
| AgentLens-controlled warnings | PASS: persistence failures do not echo credential-bearing exception text |
| Ordinary errors / metrics | PASS: readable error details and token counts preserved |

The Python corpus includes 15 credential-message variants: complete synthetic
keys, masking, ellipses, spaced masks, partial hints, prefixes/suffixes, bearer
values, Basic/Digest headers, nested/escaped error representations and hint
fields. Additional typed 401/403 tests use opaque synthetic material that cannot
be identified by credential-pattern matching. The original exception still
propagates unchanged to the application; only AgentLens's captured representation
is sanitized. Node checks inspect the actual JSON written by its SDK as well.

### Verification

- Full Python suite: **125 passed**, one existing upstream LangChain warning.
- Focused privacy/security, remote-evidence/opt-in and provider suites: **44 passed**.
- Ruff using CI paths: PASS.
- mypy using CI paths: PASS, 24 source files.
- Current checkout doctor: healthy, all six checks passed.
- Current checkout evaluation: 16/16 category/original-step matches, 8/16
  abstentions, zero errors/false positives/false negatives, 0/8 confident-wrong.
- Node: TypeScript build and consumer type checks PASS; **9/9 tests passed**
  directly in the checkout using installed dependencies and local fetch stubs.
- Git whitespace check: PASS. Generated runs, caches, build outputs and private
  files remain ignored and unstaged.

### Live evidence and remaining limits

PREVIOUS SUCCESSFUL OPENAI LIVE VALIDATION: **PRESERVED**. The existing successful
matrix and its inspection record have identical SHA-256 hashes before and after
this repair. That successful attempt is not replaced by the **LATER INVALID-KEY
ATTEMPT**, which remains a separate authentication rejection and the origin of
the privacy finding. No fresh live test is needed to establish this synthetic
repair, and none was made. Anthropic live validation remains unverified; external
developer validation remains zero.

Historical raw traces are not retroactively rewritten or certified safe. Keep
the earlier rejected-request trace private; use the repaired reader/export path
and review output before sharing. Outside typed authentication exceptions,
redaction remains recognition-based, not a universal guarantee for arbitrary
unlabeled secrets, custom encodings or malicious provider formats. Node's
credential-bearing error omission is intentionally more conservative than Python
text redaction and may retain less explanatory detail. Application logging,
original rethrown exceptions, provider/SDK debug logging and external logging
systems are outside AgentLens's controlled-output guarantee.

PRIVACY BUG: **FIXED for the identified capture paths and covered adversarial cases**.
RELEASE IMPACT: **RESOLVED for this privacy blocker**, not a blanket product or
multi-provider beta sign-off. No observed tested credential fragment survives in
newly captured AgentLens artifacts. Existing historical files still require care.

The pre-existing report edits were preserved. Source/test/report changes are local
and unstaged. Committed: no. Pushed: no. Published: no. Deployed: no.
