# Modules 1-2 Beta Support Contract

Audited September 16, 2026. Source checkout 0.1.3, not a claim about the older
published package. "Tested" below means offline protocol/regression tests unless
explicitly stated otherwise. Neither provider was live verified in this audit.

## Capture Matrix

| Capability | Python | TypeScript | Verification / boundary |
| --- | --- | --- | --- |
| Local named run | Sync and async decorator | Awaited async callback | ContextVar / AsyncLocalStorage isolation tested |
| OpenAI normal calls | Chat Completions + Responses | Chat Completions | Real SDK objects, local transports; no live calls |
| Anthropic normal calls | Messages | Messages | Real SDK objects, local transports; no live calls |
| Provider errors | Captured and original exception retained | Captured and original rejection retained | Error/cancellation tests |
| System/messages | `messages`, `system`, `instructions`, Responses input | Chat messages / Anthropic system | Recorded context, not hidden reasoning |
| Tool definitions | Captured in LLM span, normalized on read | Captured in LLM span | No universal JSON Schema evaluator |
| Tool requests / arguments | Captured and correlated by tool-use ID | Captured and correlated by tool-use ID | Request is not proof of execution |
| Tool results | Next provider request or manual API | Next provider request or manual API | Use manual API if result is never sent back |
| Tool execution / duration | No general function interceptor | No general function interceptor | Tool runtime/side effects are not automatically timed |
| Usage | Provider-supplied fields | Provider-supplied fields | Unknown usage is not measured zero; no billing reconciliation |
| LLM latency | Start-to-result/stream-end wall duration | Request-to-response duration | Includes transport/provider retries; not separate tool duration |
| Price | Historical estimates; unknown models remain unknown | Historical estimates | Not exact billed spend; Module 3 expansion deferred |
| OpenAI streams | Chat/Responses create with `stream=True`, sync/async | Not captured | Consume/close inside run; final snapshot, not chunk log |
| Anthropic streams | create iterator + Messages stream manager, sync/async | Not captured | Close/context-manager required for early exits |
| Responses | Sync/async create and its streams | Not supported | Server-side previous context is referenced, not fetched |
| Memory/state | Explicit copied snapshots | Explicit copied snapshots | No universal automatic memory capture |
| State diff | Replay `d`, added/removed/changed fields | Through Python CLI reading saved Node JSON | Lists are whole values; comparison precedes display truncation |
| Parent-child runs | Nested decorators / explicit propagation | Explicit `parentRunId` / parent context | Node does not automatically infer nested parents |
| Inspection | CLI and generated local HTML | Python CLI reads compatible JSON | No Node CLI required/parity implied |
| Replay | Forward/back/full recorded span | Through Python CLI | No execution rerun or fix validation |
| Watch | Poll changed saved snapshots | Observes saved Node snapshots | Not live provider-event capture |
| Persistence | Atomic replacement, private temporary file, fsync | Atomic rename, private temporary file, fsync | Different UUID runs separate; shared file is last writer wins |
| Export privacy | Best-effort anonymize + residual gate | Python CLI export of saved traces | Raw local capture remains sensitive |

Tested dependency contracts: Python OpenAI 2.41.x, Anthropic 0.107.x,
LangGraph 0.6.x; Node OpenAI 6.49.x, Anthropic 0.125.x. Check extras/peer ranges
in packaging before changing SDK versions. Subclass overrides bypassing patched
resource methods, raw HTTP clients, beta endpoints and patch combinations are
not guaranteed. Configuration passthrough is not proof of every proxy deployment.

## Integration Tool Matrix

| Integration | Selection | Arguments | Execution | Result | Tool error | Schema | Automatic/manual |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Python OpenAI Chat/Responses | Auto | Auto | Not intercepted | Auto on resubmission | Output evidence / explicit record | Auto | `record_tool_result` for final/orphan results |
| Python Anthropic Messages | Auto | Auto | Not intercepted | Auto on resubmission | `is_error` / error output / explicit record | Auto | Same manual boundary |
| Node OpenAI/Anthropic | Auto, non-streaming | Auto | Not intercepted | Auto on resubmission | Provider/tool-result fields; not every thrown tool error | Auto | `recordToolResult` or caught run exception |
| LangGraph wrapper | Provider capture if eligible | Provider capture if eligible | Aggregate invoke / top-level updates | Aggregate/node data plus provider result messages | Graph exceptions | Provider calls only | Patch before compile; no universal tool executor interception |
| CrewAI / AutoGen / PydanticAI | Conditional | Conditional | No native coverage | Conditional | Conditional | Conditional | Provider passthrough only, not native framework integrations |

Unreturned exceptions inside a tool can be captured at the enclosing decorated
run boundary, but do not automatically gain the correct tool ID/name/duration.
The minimum beta contract is explicit, not an implicit promise of function tracing.

## Streaming and Incomplete Runs

Python accumulates content/tool arguments and emits one LLM span on completion,
closure or error. Tool request/result updates share one call ID. Raw chunks are
not persisted. EOF without a provider completion marker now remains `partial`.
Missing usage remains unavailable. Partial argument strings may remain strings,
not valid tool input objects. They must not be mistaken for executed calls.

An abandoned unclosed stream or process killed before save may leave no file.
Consume and close streams inside the run. Await spawned tasks; detached tasks
after finalization are outside the supported persistence contract. Raw Responses
and Anthropic helper APIs not exercised by tests remain experimental.

Run `status=error` can include a recovered historical error; it is not by itself
proof of a wrong final answer. The diagnosis has its own evidence decision.
Nested children have independent outcomes. A parent that handles a child failure
can finish successfully. A missing unsaved child cannot be inferred from a parent
ID tree; no distributed completeness guarantee is made.

## Explicit State Boundary

Use `record_memory_snapshot("before_lookup", state)`, perform the workflow step,
then `record_memory_snapshot("after_lookup", state)`. Each snapshot has its own
original span index and label. JSON-like state is copied; arbitrary objects are
represented conservatively and nesting has a capture depth limit. These are
snapshots of supplied values, not pointers into evolving application state.

In replay, `d` compares the latest two recorded snapshots at/before the cursor;
`f` shows full captured span JSON. Local inspection can display raw secrets.
Anonymization must operate on the entire trace before export; redacted diffs
can conceal a change between two secrets and must not imply original equality.

## Supported / Partial / Manual / Not Supported

- **Supported offline-tested scope:** Python sync/async calls listed above,
  local storage, narrow evidence rules, recorded inspection, best-effort exports.
- **Partial/experimental:** LangGraph scoped wrapper, conditional framework
  passthrough, remote diagnosis, source-specific schema/contradiction checks,
  streams within the tested protocols, hierarchy without distributed completeness.
- **Manual:** Final tool results not returned to a provider, state boundaries,
  Node parent propagation, active `save_run()` checkpoints, outcome feedback,
  independent ground truth, review/redaction of proprietary content.
- **Not supported:** Universal framework tracing, TS streams/Responses, automatic
  tool execution timing, universal automatic memory, deterministic rerunning,
  automatic fix verification, arbitrary factual hallucination detection,
  calibrated correctness probabilities, server/cloud live event transport.

## Diagnosis Contract

`unknown` is a valid outcome and not a certificate of health. All heuristic
positive candidates currently receive an evidence score of 0.85; these numbers
are rules, not calibrated probabilities. Schema findings use separate static
scores (0.95/0.97) and explicit contradictions 0.80. No user calibration exists.

The root-cause step is the earliest *supported candidate* in original span order,
not automatically the first exception. Secondary categories are other detected
candidates, not a validated causal chain. A same-step tie uses detector order;
ambiguous routing destinations now abstain rather than selecting tool-list order.

Remote output must pass schema/citation checks AND match a candidate independently
recomputed from the existing local rules, including earliest origin, explanation,
suggested-fix template, secondary categories and full supporting citations.
The provider sees a redacted candidate; validation compares that representation
without mistaking redaction for new causal evidence. Scores may be lowered, not
raised above local evidence strength. Untrusted extra metadata is discarded.

This is a deliberately restricted contract, not general semantic entailment:
even correct free-form paraphrases are rejected. Accepted remote output adds no
category coverage beyond local rules and is not independent corroboration of
their accuracy. Unsupported proposals fall back visibly to local rules/unknown.
The hostile regression now passes; the report retains the original failure and
appends repair results. Technical readiness for limited external beta awaits live
OpenAI/Anthropic validation. External-developer accuracy and usefulness are a
separate product-validation gate, not necessarily missing implementation.

Every generated fix is `unverified`. Similarity reports a separately recorded
developer outcome only when exact attempted fix, status, source and date exist.
Neither similarity nor a score establishes that a fix worked.

## Narrow Active Visibility Design (Deferred)

Keep the existing JSON reader and atomic writer. Proposed follow-up: allocate
the in-flight LLM span at call start, then update that same ID at completion;
publish a `running` snapshot at run start and logical evidence boundaries.
Snapshot tool-result updates too, not only append operations. Serialize mutations
and snapshot creation under a per-run lock, and use monotonic snapshot revisions
so an older concurrent completion cannot overwrite a newer final state.

Use a single local writer per run, flush the final snapshot, and warn on failure
without replacing the application result. Coalesce disk writes only with an
explicit durability contract; it cannot honestly guarantee zero loss on SIGKILL.
Retain raw events in memory; no server is needed. `watch` can poll the evolving
atomic file and print running/partial/final states. Test cancellation, concurrent
completion, early stream close, disk errors, and readers racing replacement.

This changes capture lifecycle and durability, not just watch formatting. It was
not implemented in this audit. Current explicit `save_run()` checkpoints already
work and are the beta workaround; missing events before checkpoint remain a risk.
