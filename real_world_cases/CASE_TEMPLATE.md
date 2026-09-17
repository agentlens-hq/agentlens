# Real-World Case Template

Create one folder per beta-user case.

```text
real_world_cases/<case_name>/
├── trace.json
├── expected_diagnosis.json
├── actual_diagnosis.txt
└── notes.md
```

## `trace.json`

Anonymized AgentLens run JSON. Remove secrets, API keys, user data, internal URLs, and proprietary prompts unless the user explicitly approves sharing them.

## `expected_diagnosis.json`

Record independently BEFORE viewing AgentLens's answer. Do not fill this from
the model's output. If the cause is uncertain, use `unknown` and step `0`.
Keep the original dated ground truth in `notes.md`; append corrections with
their reason rather than replacing the original after seeing the diagnosis.

```json
{
  "evaluation_population": "external_developer",
  "root_cause_category": "tool_selection",
  "failed_at_step": 2,
  "confidence_min": 0.6,
  "confidence_max": 1.0
}
```

Use `regression` for engineered examples (including maintainer-run OSS examples),
`internal_natural` for unengineered failures in maintainer-operated agents, and
`external_developer` only for independently provided developer failures. An
unlabeled saved case is `unclassified`, not automatically external. These are
manual provenance declarations, not authenticated user counts.

Legacy `confidence_min`/`confidence_max` fields above are descriptive; the current
evaluator does NOT enforce those ranges. Never call them calibration tests.

## `actual_diagnosis.txt`

Paste the CLI output:

```bash
agentlens diagnose <run_id>
```

## `notes.md`

Record:

- whether the user confirmed correctness
- whether the fix worked
- what was confusing
- whether they would pay
- any trust failures

## Blind Review Protocol

1. Save the captured run; do not use `diagnose`, `runs show`, or `runs view` yet
   (inspection commands may also calculate/display a diagnosis).
2. Have the developer inspect their own logs or raw local JSON and record the
   trace ID, observed outcome, proposed cause/step, explanation and proposed fix,
   with a timestamp. Leave unavailable ground truth explicitly unknown.
3. Run diagnosis. Preserve the actual category, original step, source, evidence,
   confidence and exact suggested fix separately from the expectation.
4. Ask whether the category/step were correct, whether the explanation helped,
   time saved, fix helpful, problem resolved, confidence believable, and repeat use.
   A useful diagnosis is not necessarily a correct diagnosis or a resolved fix.
   Ask "Without AgentLens, how would you have found this?" and "Did this actually
   save you debugging time?" Record concrete comparisons with their existing tools.
5. Record one row per interaction in `feedback/users.csv`; use pseudonymous IDs.
   Count distinct developers separately from interactions. Do not count blanks
   as negative feedback or count maintainer tests as developers.
6. Manually review the anonymized export before sharing. Run `agentlens evaluate`
   from the checkout to replay saved traces; fixtures and independent traces have
   separate population summaries. A healthy control that abstains is a correct
   abstention, not a successful positive diagnosis.

## Optional Local Fix Outcome

To retain a developer's outcome with a local trace, use existing run metadata:

```json
{
  "metadata": {
    "fix_feedback": {
      "status": "resolved",
      "fix": "The exact change the developer actually tried",
      "source": "developer",
      "recorded_at": "2026-09-16"
    }
  }
}
```

Allowed statuses: `helpful`, `resolved`, `did_not_resolve`. Absent/incomplete
feedback is unverified. Similarity results expose this separately as
`developer_fix_outcome`; their newly generated `fix` is always `unverified`.
An outcome is a manual report, not proof that the same change will work elsewhere.
No new command, database, or automated fix execution is introduced.
