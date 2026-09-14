# Release Verification

Run from the checkout:

```sh
python -m pip install -e ".[dev,openai,anthropic]"
python -m unittest discover -s tests -v
python -m ruff check agentlens.py agentlens_core agentlens_sdk agentlens_engine server/app.py tests
python -m mypy --no-incremental agentlens.py agentlens_core agentlens_sdk agentlens_engine
agentlens doctor
agentlens evaluate
python -m build
python tests/artifact_smoke.py dist/runlens-0.1.3-py3-none-any.whl
```

Run `npm ci` and `npm test` in `agentlens_sdk_ts/`. Node tests import built output
and compile a consumer against the exported declarations. No paid keys are used.
The artifact smoke test creates a clean environment without optional dependencies
and runs outside the checkout. CI runs Python 3.9, 3.10, 3.11 and 3.12, plus Node
20 and 22. Local evidence and unresolved gates are in `audit_repair_report.md`.

## Corpus

Packaged `agentlens_engine/corpus/positive/` contains six known synthetic failures;
`healthy/` contains eight healthy or partial runs that should abstain. The two
checkout OSS cases are developer-operated fake-model workflows, not real users.
Do not present these counts as live-provider accuracy or market validation.

Add an anonymized case under `real_world_cases/<case>/` with `trace.json`,
`expected_diagnosis.json` and `notes.md`. Expectations use `root_cause_category`
and `failed_at_step` (original index; zero for unknown). The evaluation reports
category and step matches separately, including raw counts and abstentions.

Two legacy fixture corrections are intentional: separate retries now have unique
provider call IDs; overflow begins at step 2 where input context is omitted, not
at the final step 4 exception. The original failure evidence was retained.

## Boundaries

Remote evidence validation checks schema, references and quoted observations; it
cannot prove that a model's causal interpretation is true. Models and local rules
can still miss failures. The local context/goal detectors require explicit evidence
and will abstain on many subtle semantic failures.

Redaction is best effort. Unknown formats, encoded secrets and proprietary content
need manual review. Never share raw traces or expose the unauthenticated server to
the public internet. Local trace files deliberately preserve raw debugging data.

Run files use atomic last-complete-snapshot replacement. This protects JSON from
partial writes, but does not merge concurrent writes to an explicitly shared path.
Streams must be consumed or closed before a run exits; detached tasks and abandoned
streams have no late-persistence guarantee. Watch displays saved snapshots, not
live stream events. Pricing is a historical estimate; missing pricing remains unknown.
