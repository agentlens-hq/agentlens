# Contributing to AgentLens

Thank you for helping developers debug agent failures. Useful contributions include
reproducible bugs, diagnosis regressions, provider capture fixes, documentation,
accessibility improvements, and small, well-tested changes.

Read the [README](README.md) for supported behavior and limitations. AgentLens is
beta software: evidence quality and user trust take priority over feature count.

## Start Here

1. Search [existing issues](https://github.com/agentlens-hq/agentlens/issues) and
   [pull requests](https://github.com/agentlens-hq/agentlens/pulls) to avoid duplicates.
2. For a substantial feature, dependency, public API, or architecture change, open
   an issue describing the problem and proposed scope before implementing it.
3. Fork the repository, create a descriptive branch from current `main`, and keep
   each pull request focused on one problem.
4. Add a regression test for a bug fix and document any changed public behavior.
5. Open a pull request against `main` with evidence and verification results.

Small typo fixes do not need an issue first. Do not mix unrelated cleanup,
reformatting, package moves, or version bumps into a focused fix.

## Local Setup

Python CI covers 3.9, 3.10, 3.11, and 3.12. Preserve Python 3.9 compatibility.
Use an isolated environment and your fork's clone URL:

```sh
git clone https://github.com/<your-username>/agentlens.git
cd agentlens
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,openai,anthropic]"
agentlens doctor
agentlens demo --no-browser
```

On Windows, activate with `.venv\Scripts\activate`. Do not stage `.venv/` or any
environment contents, even if your local ignore configuration differs.
Provider keys are not required for the offline demo or the normal regression suite.
Installation downloads dependencies; the demo itself is offline.

## Repository Map

| Area | Purpose |
| --- | --- |
| `agentlens.py` | Public Python entry points and CLI |
| `agentlens_sdk/` | Python provider instrumentation and capture |
| `agentlens_core/` | Shared core utilities |
| `agentlens_engine/` | Preprocessing, classification, diagnosis, evaluation corpus |
| `agentlens_sdk_ts/` | TypeScript SDK with its own support boundaries |
| `server/` | Optional local/self-host server, not a public managed service |
| `tests/` | Python regression and artifact checks |
| `real_world_cases/` | Reviewed, shareable evaluation cases |
| `index.html`, `website/` | Static public website |
| `docs/` | Usage, operating notes, and verification documentation |

Keep changes in the appropriate layer. Website fixes must not modify diagnosis
behavior; SDK fixes must preserve the wrapped provider's normal behavior.
Do not add UI, hosted services, billing, authentication, or other product expansion
to a bug-fix PR without prior scope agreement.

## Coding and Diagnosis Rules

- Prefer small, readable functions and the repository's existing conventions.
  Explain non-obvious decisions; avoid comments that only restate code.
- Keep public behavior backward-compatible unless a breaking change is explicitly
  discussed. Update examples and docs when interfaces change.
- Keep optional provider dependencies optional. Base package imports must work
  without OpenAI, Anthropic, or server extras installed.
- Preserve sync/async run isolation, tool-call correlation, stream cleanup,
  original step references, and graceful error handling when touching capture.
- Every diagnosis must be grounded in trace evidence. Missing context or a
  successful process exit must not become a confident correctness claim.
- Preserve abstention and source labels. Confidence scores are evidence strength,
  not calibrated probabilities. Do not inflate scores to make tests pass.
- For diagnosis changes, add both a failure regression and a healthy/ambiguous
  counterexample where relevant. Do not weaken expected results to hide regressions.
- Do not claim universal framework support, production accuracy, live-provider
  verification, customer adoption, or time savings without supporting evidence.
- AI-assisted contributions are welcome, but the contributor must understand,
  review, and test the patch and is responsible for its accuracy and provenance.

## Required Verification

Run checks appropriate to your changes and report exactly what ran. The current
[CI workflow](.github/workflows/ci.yml) is the source of truth for merge checks.
Do not disable checks or delete tests to make a PR pass.

### Python changes

From the repository root:

```sh
python -m unittest discover -s tests -v
python -m ruff check agentlens.py agentlens_core agentlens_sdk agentlens_engine server/app.py tests
python -m mypy --no-incremental agentlens.py agentlens_core agentlens_sdk agentlens_engine
agentlens doctor
agentlens evaluate
python examples/anthropic_broken_agent.py
python examples/openai_broken_agent.py
```

Use fake providers or local transports for automated tests. Do not make CI require
paid API calls, personal credentials, or access to external private systems.
If a live-provider test is explicitly needed, make it opt-in, state its cost/network
requirements, and never include its raw output or credentials in the PR.

For packaging changes, run `python -m build` and the wheel smoke test documented in
[release verification](docs/release_verification.md). Verify the artifact outside
the checkout without optional dependencies. Do not commit generated artifacts.

### TypeScript changes

CI tests Node 20 and 22. From `agentlens_sdk_ts/`:

```sh
npm ci
npm test
```

This includes the build, exported-type consumer check, and local protocol tests.
Keep the lockfile consistent when an approved dependency change requires it.

### Website and documentation changes

The public homepage needs no build framework:

```sh
python -m http.server 8765 --bind 127.0.0.1
node --check website/app.js
git diff --check
```

Inspect `http://127.0.0.1:8765/` on desktop and mobile. Check links, keyboard focus,
contrast, reduced-motion behavior, readable overflow handling, and browser errors.
Website-only changes do not require unrelated product refactors. Include before/
after screenshots for visual changes, without private data.

## Privacy and Test Data Policy

Never commit credentials, personal or customer data, private provider responses,
or raw debugging traces. Specifically exclude:

- `codex.md`, `CLAUDE.md`, and other private working logs.
- `.env` and other environment/credential files.
- `.agentlens/`, `agentlens_run.json`, generated run JSON, and anonymized exports.
- `.agentlens_server.db`, local databases, private outreach and feedback records.
- Virtual environments, caches, `*.egg-info/`, `node_modules/`, and build output.

Ignore rules are a guardrail, not proof of safety. Do not force-add ignored files.
Anonymization is best-effort; manually inspect exported data before sharing it.
An `.anonymized.json` name is not a guarantee that a file is safe.

Prefer synthetic minimal reproductions. A real trace may become a committed
regression case only if you have permission to share it and have reviewed it for
credentials, PII, proprietary content, and identifying metadata. Record provenance
without identifying the user. Use `trace.json`, `expected_diagnosis.json`, and
`notes.md` under `real_world_cases/<case>/`, following
[the case template](real_world_cases/CASE_TEMPLATE.md) and release-verification
instructions. Label synthetic, developer-operated OSS, and real-user cases honestly.

## Reporting Bugs and Security Issues

For a normal bug, include your Python/Node and provider SDK versions, OS, install
method, exact reproduction command, expected versus actual behavior, and a minimal
sanitized example. Mention whether the run used fake/local or live providers.
Avoid posting full traces when a small synthetic reproduction is enough.

Do not disclose exploitable vulnerabilities, leaked credentials, or private data
in public issues or PRs. Use GitHub's private vulnerability reporting if enabled;
otherwise contact **hello@agentlens.run** with a non-sensitive summary to arrange
private disclosure. Do not send active secrets or raw customer traces by email.
If a key was exposed, revoke/rotate it; deleting a file does not remove Git history.
No response-time guarantee or bug bounty is implied by this guide.

Test only systems and data you are authorized to use. Do not attack production
services, intercept private traffic, bypass authentication, or expose the optional
unauthenticated server to the public internet.

## Pull Request Checklist

- [ ] The branch targets `main` and addresses a single clear problem.
- [ ] Description explains the problem, implementation, behavior changes, and limits.
- [ ] Relevant regression tests, healthy counterexamples, and docs are included.
- [ ] Verification lists commands, results, and anything not tested with its reason.
- [ ] Screenshots or sanitized examples are included where helpful.
- [ ] No secrets, raw traces, private logs, generated output, or unrelated edits are staged.
- [ ] New dependencies and public API changes were discussed and justified.
- [ ] All required CI checks pass; known risks are disclosed rather than hidden.

Before committing, inspect the actual staged diff:

```sh
git status --short
git diff --check
git diff --cached --name-only
git diff --cached
```

Stage explicit relevant paths rather than blindly adding everything. Use a clear,
descriptive commit message and PR title. Maintainers may request changes or decline
work that is out of scope. Do not self-merge, publish packages, deploy the website,
change release versions, or bypass branch protection without maintainer approval.

## Community and Licensing

Be respectful and specific. Critique code and evidence, not people. Harassment,
discrimination, threats, doxxing, spam, and sharing others' private information are
not acceptable. Maintainers may remove harmful content or restrict participation.
Report sensitive conduct concerns privately to the contact above rather than
escalating a public argument.

Submit only work you have the right to contribute. Contributions are intended to
be distributed under the project's existing [MIT License](LICENSE). Preserve
required copyright notices and attribute third-party assets and code. Do not copy
unlicensed code, confidential work, or branding that implies an endorsement.
No separate CLA or sign-off process is asserted by this guide.
