# Changelog

## 0.1.3 (beta, September 20, 2026)

- Make remote diagnosis explicit opt-in; redact and bound provider requests.
- Harden timeline JSON embedding, credential scanning and run-derived paths.
- Preserve provider resource protocols, streaming lifecycle, tool IDs, run context
  and atomic persistence. Separate incomplete states from completed execution.
- Replace unsupported topic/name inferences with evidence rules and abstention;
  retain original span identity, validate diagnosis references and preserve fixes.
- Ship positive and healthy regression resources in the wheel; add provider,
  security, malformed-input, artifact and Node-package checks to CI.
- Correct cost, CLI failure handling, framework/privacy and validation claims.
- Redact credential hints in captured authentication errors before persistence.
- Record malformed provider responses and failed/incomplete Responses bodies as
  errors or partial execution instead of successful completion.
- Avoid quadratic credential/email scans on long ordinary tool output.
- Add hostile boundary regressions for provider errors, recovery, cancellation,
  concurrent run isolation and unusual output; preserve documented P2 limits.
- Document the provider extra required by the public OpenAI quickstart.

This remains beta software. Scores are not calibrated probabilities.
The Node SDK has a narrower non-streaming capture scope than Python.
