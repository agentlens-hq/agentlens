# AgentLens

Local Python trace capture and evidence-based diagnosis for agent failures.
AgentLens reports an original trace step, the supporting evidence, and a suggested
fix when a rule can support them. Otherwise it reports **insufficient evidence**.

## Install and Try

This checkout prepares version **0.1.3**; it has not been published by this repair.
The published `pip install runlens` release may not contain these changes.

```bash
git clone https://github.com/agentlens-hq/agentlens.git
cd agentlens
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[openai,anthropic]"
agentlens doctor
agentlens demo --no-browser
```

On Windows, activate with `.venv\Scripts\activate` instead. Use the activated
environment's CLI; a global `agentlens` command may belong to an older install.

The demo simulates a broken agent locally and never calls a provider, even when
API keys are set. Doctor checks local mechanics, not real-world diagnosis quality.

## Capture a Run

Two lines enable instrumentation; a decorator groups and **saves** the run.
Calling `init()` alone does not persist a grouped run.

```python
import agentlens
agentlens.init()

from openai import OpenAI
client = OpenAI()  # Uses your OPENAI_API_KEY for your own provider requests.

@agentlens.run(name="support_agent")
def support_agent(query):
    return client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": query}],
    )

support_agent("Find the status of customer C17.")
```

`async def` decorators and async provider clients are supported. Await child
tasks before the decorated function exits. Independent decorated agents get
separate run IDs; nested decorators create child runs. Detached background tasks
are not guaranteed to be persisted after their parent run finishes.

Run snapshots are saved to `.agentlens/runs/<run_id>.json`. Use
`agentlens.save_run()` inside a run for a partial snapshot. Save failures warn
without replacing your agent's result or original exception. Explicitly shared
save paths use atomic last-complete-snapshot replacement, not span merging.

Tool requests are captured from provider responses. Tool results are correlated
when submitted in the next provider request, or explicitly:

```python
agentlens.record_tool_result(
    tool_name="lookup", tool_use_id=call_id, input=arguments, output=result
)
```

Use a new provider call ID for each retry. Re-recording an existing ID updates
that result, including a legitimate `None` output.

## Inspect and Diagnose

```bash
agentlens runs list
agentlens runs show <run_id>
agentlens diagnose <run_id>                    # Offline, even with API keys set
agentlens runs prompt <run_id> --step 2        # Original trace step, not LLM-call ordinal
agentlens runs view <run_id>                   # Local HTML; prints path if browser unavailable
agentlens runs replay <run_id>
agentlens runs stitch <run_id>
agentlens watch                               # Changed saved snapshots, not live event streaming
agentlens stats                               # All runs; known cost subtotal and unknown-price count
agentlens similar <run_id>
agentlens clusters
agentlens anonymize <run_id>
agentlens feedback-template <run_id>
agentlens evaluate
```

Example from the deterministic demo, abbreviated:

```text
SOURCE:
  Heuristic fallback
ROOT CAUSE:
  tool_selection
FAILED AT:
  Step 2 (search_web)
WHY:
  Step 2 called 'search_web', whose error explicitly directs this operation to 'query_db'.
FIX:
  Route this operation to 'query_db' as the error requests; distinguish its supported operation.
EVIDENCE STRENGTH: observed
Confidence score (not a calibrated probability): 0.85
```

Categories: `tool_selection`, `loop`, `cascade`, `context_pollution`,
`state_drift`, `overflow`. Local rules are intentionally narrow: explicit
routing errors, repeated failed calls without progress, downstream reuse of
flagged fields, or explicit evidence of conflicting instructions/goal/context
loss. Names, topics, repetition alone, and preprocessing truncation are not proof.
These rules do not reliably infer subtle semantic errors or model intent.

Scores express evidence strength, **not calibrated odds of correctness**.
A completed process is not proof of a correct answer. Partial/running/cancelled
runs retain their execution status. Absence of a detected failure is not a safety
certification. Hallucination checks cover constrained schema violations and
explicit same-entity field contradictions; they do not verify arbitrary facts.

## Verified Capture Scope

Python protocol tests use real SDKs with local HTTP transports, not paid calls:
OpenAI 2.41.0 (Chat Completions and Responses) and Anthropic 0.107.0 (Messages),
sync/async, normal calls, iterator streams, tool results, context managers and
configured clones. Provider extras constrain these tested minor versions.
Aliases, ordinary subclasses, existing clients and custom transports retain their
normal resource methods. Overrides that bypass those methods, raw HTTP clients,
beta endpoints and third-party instrumentation combinations are not guaranteed.

Consume streams within the decorated run. On early exit, explicitly close them
or use their context manager. Unclosed abandoned streams cannot guarantee capture.

LangGraph 0.6.11: call `agentlens.patch_langgraph()` **before compiling**.
`invoke`/`ainvoke` record aggregate results. Explicit
`stream_mode="updates"` records top-level node updates; `values` and other
modes are not interpreted as nodes. `with_config()` preserves this wrapper.
Precompiled graphs, batch, subgraph/multi-mode node attribution are not supported.
Provider calls made through supported SDK methods can still be captured.
No universal CrewAI/AutoGen/PydanticAI or arbitrary raw-API interception is claimed.

The Node package in `agentlens_sdk_ts/` supports awaited non-streaming OpenAI Chat
and Anthropic Messages calls. Its narrower support is **not Python parity**.
See its README for build and protocol limitations.

## Privacy and Remote Diagnosis

Local capture and default diagnosis store/process traces locally. Raw capture may
contain secrets, personal information, tool output, and provider error text.
Keep `.agentlens/`, `.env`, generated exports and private logs out of Git.

Remote diagnosis requires explicit opt-in:

```bash
agentlens diagnose <run_id> --provider openai
# or --provider anthropic
```

Programmatic equivalent:
`diagnose_run(run_json, provider="openai", timeout=10)` from
`agentlens_engine.diagnose`. The chosen provider receives a redacted compact
trace containing selected prompts, tool definitions, inputs/outputs and errors.
It receives no more than 60 KB; larger payloads fall back to local rules.
Connection timeout: 3 seconds; read timeout: at most 10 seconds per request;
SDK retries: zero; one extra attempt only for invalid diagnosis JSON.
These are transport timeouts, not a hard total wall-clock deadline.
Provider failures or invalid evidence fall back to local rules and are labeled.
No provider is selected merely because a key exists.

`anonymize` and `upload prepare` use the same best-effort credential/PII policy
as server ingestion. Review exports manually: proprietary facts, arbitrary names,
encoded secrets and unknown credential formats cannot be guaranteed removed.
Preparation writes files locally; it does not upload them.

Optional person-name detection:

```bash
python -m pip install "runlens[pii]"
python -m spacy download en_core_web_sm
```

Without that model, built-in credential patterns and explicit PII keys still work,
but free-text name detection is unavailable. The optional server remains an
unauthenticated local/self-host component; do not expose it publicly. Its residual
scanner rejects known patterns, not all possible sensitive information.

## Evaluation and Beta Status

`agentlens evaluate` runs the packaged positive and healthy corpus offline,
plus explicitly saved `real_world_cases/` in the working directory.
The packaged corpus has 6 synthetic positives and 8 healthy/abstention cases.
The checkout also has 2 developer-operated OSS validation cases, not customer
traces. The command reports raw category/step matches, false positives/negatives,
abstentions and runtime. These small regression counts do not estimate accuracy
on unseen users. No zero-false-positive or live-provider benchmark is claimed.

Real external users, confirmed usefulness and payment intent remain unverified.
Stay in Phase 3; regression success alone is not evidence of product-market fit.
For case format and verification commands see [release verification](docs/release_verification.md).
