# Live Provider Validation

Current status: **BLOCKED - provider credentials unavailable to this task**.

## Result

- Provider: none
- Date checked: 2026-09-17
- Environment keys found: none
- `OPENAI_API_KEY`: not present
- `ANTHROPIC_API_KEY`: not present

## Workflow

No live OpenAI or Anthropic workflow was run because neither provider API key
was available to the task process. Only environment-variable presence was
checked; values were not displayed, private files were not searched, and no
provider request was attempted. Earlier June 2 verification was also blocked.

## Trace Quality

Not evaluated for a live provider in this pass.

## Diagnosis Quality

Not evaluated for a live provider in this pass.

## Issues Found

- Live provider validation is still the highest-priority technical validation gap.
- Local mocked-provider tests and maintainer-run OSS examples are not live
  provider validation or independent developer evidence.

## Next Attempt

Configure credentials privately in the environment used to launch the validation
process. Never place values in prompts, committed commands/scripts, fixtures,
screenshots, or trace content. Do not reuse credentials previously exposed in
documents. Models must be confirmed active and available to the account at run
time; do not reuse the old `claude-3-5-sonnet-latest` example configuration.

Use tiny requests and harmless local tools with synthetic business data. Record
the actual provider, model, SDK version, run ID and observed result for each row.
Do not count an example's fake-provider fallback as a live success.

| Verification | OpenAI | Anthropic |
| --- | --- | --- |
| Normal LLM request | BLOCKED | BLOCKED |
| Tool selection and arguments | BLOCKED | BLOCKED |
| Tool result capture | BLOCKED | BLOCKED |
| Local tool error capture | BLOCKED | BLOCKED |
| Async request | BLOCKED | BLOCKED |
| Completed stream | BLOCKED | BLOCKED |
| Interrupted/partial stream | BLOCKED | BLOCKED |
| Reported token usage | BLOCKED | BLOCKED |
| Recorded latency | BLOCKED | BLOCKED |
| Saved trace inspection/replay | BLOCKED live | BLOCKED live |
| Offline diagnosis of live trace | BLOCKED | BLOCKED |
| Explicit remote diagnosis and source/fallback inspection | BLOCKED | BLOCKED |
| Responses API capture | BLOCKED | Not applicable |
| Actual credential absent from saved trace | NOT TESTED live | NOT TESTED live |

After each run, inspect the saved JSON and compare it locally against the actual
credential value held in memory. Report only pass/fail, never the value or a
matching trace excerpt. Check obvious secret/header patterns as well. If a key
is present, stop sharing the trace and rotate the affected credential. Keep all
raw live output under ignored local storage; commit only sanitized summaries.

Diagnosis should abstain on healthy/insufficient evidence. A useful tool-failure
case must be observed rather than hardcoded as a diagnosis. An unsupported remote
proposal must visibly fall back; do not relabel fallback as successful LLM RCA.

## Separate Exit Gates

**Engineering:** implementation/offline checks pass within the documented support
scope; live OpenAI and Anthropic validation is still outstanding.

**Product:** independent developers, real-user accuracy, usefulness and repeat use
are unvalidated. This is not an assertion of missing implementation.

Only after the live matrix passes is the engineering statement justified:
"Modules 1 and 2 are technically ready for limited external beta within the
documented support scope; real-user accuracy and usefulness remain unvalidated."
Then stop adding internal fixtures and use the blind review protocol with three
developers on their own agents.
