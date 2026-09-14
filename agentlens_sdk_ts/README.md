# Node Capture SDK

Build locally (not published by this repair):

```sh
npm ci
npm test
```

CommonJS output is `dist/index.js`, usable through `require` or ESM import.
Declarations are in `dist/index.d.ts`. Tests exercise this built output.

```js
const {init, run} = require('agentlens-sdk');
init();
await run('agent', async () => {
  // Await ordinary OpenAI Chat or Anthropic Messages create() calls here.
});
```

Supported: non-streaming Chat Completions and Messages, request options/custom
fetch, constructor aliases/subclasses, APIPromise methods, tool request/result
IDs, concurrent runs, explicit AbortError cancellation, atomic local persistence.
Result messages in subsequent requests or `recordToolResult()` complete calls.
Unfinished tool calls retain a partial run status. Historical pricing estimates
do not double-count token aliases; missing usage or unknown models remain unknown.
Capture uses resource methods, not raw HTTP interception.

Not Python parity: no Responses capture, streaming capture, LangGraph wrapper,
or raw-response-only capture guarantee. Streaming calls pass through unchanged
and warn that they were not captured; do not rely on them for diagnosis.
`messages.stream()` is not instrumented. Calls must finish inside `run()`.
Calling `init()` alone does not persist orphan spans. Raw traces may include
secrets; review/redact before sharing. Errors during persistence warn, rather
than replacing the application's error/result.
