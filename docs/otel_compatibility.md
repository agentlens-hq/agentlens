# OpenTelemetry Compatibility Review

Reviewed September 16, 2026. This is a proposed mapping, not an OTel exporter or
conformance claim. No dependency or schema migration was added.

The official [GenAI conventions landing page](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
now points to the [GenAI repository](https://github.com/open-telemetry/semantic-conventions-genai).
The current [client span specification](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md)
is marked Development. Re-check versions before implementing an adapter.

| AgentLens concept | Proposed OTel relationship | Current divergence |
| --- | --- | --- |
| Named run | Agent/workflow invocation operation | UUID run ID is not a W3C trace ID |
| LLM call | Inference client span | Span currently appended on finish, not live start |
| Provider / model | `gen_ai.provider.name`, `gen_ai.request.model` | Returned model may differ; not always normalized separately |
| Tool call | `execute_tool`, tool name / call arguments / result | AgentLens merges request with result; does not measure execution duration |
| Usage | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | Provider aliases and cache token meanings need an adapter |
| Error | Error status / `error.type` | Free-text errors and historical run status need classification |
| Parent-child | Parent span context / links | Parent run IDs only; no traceparent propagation |
| Prompt/response | GenAI input/output message attributes | Content shape/privacy policy must be translated |
| Memory snapshot | Application event or future memory operation mapping | Supplied state is not a measured memory read/write |

Do not map a tool *request* to a completed execution span. Do not convert static
RCA confidence scores into telemetry correctness probabilities. Export redaction
and content consent must remain explicit; interoperability is not permission to
send raw local prompts to a collector. These are AgentLens design constraints.
