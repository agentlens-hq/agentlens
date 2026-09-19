/**
 * AgentLens Node.js SDK
 *
 * Local trace capture for AI agent debugging.
 *
 * Quick start:
 *   import { init, run, recordToolResult } from 'agentlens-sdk';
 *
 *   init();
 *
 *   await run('my-agent', async () => {
 *     const client = new Anthropic();             // auto-captured
 *     const response = await client.messages.create({ ... });
 *     return response;
 *   });
 */

import { AsyncLocalStorage } from 'node:async_hooks';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as crypto from 'node:crypto';

// ── Types ───────────────────────────────────────────────────────────────────

export interface Span {
  id: string;
  run_id: string;
  type: 'llm_call' | 'tool_call' | 'error' | 'memory_snapshot';
  ts: string;
  [key: string]: unknown;
}

export interface Run {
  run_id: string;
  name: string;
  started_at: string;
  ended_at: string | null;
  status: 'running' | 'success' | 'error' | 'cancelled' | 'partial';
  parent_run_id?: string;
  spans: Span[];
  error?: string;
}

export interface TraceContext {
  parent_run_id: string;
}

export interface InitOptions {
  /** API key (reserved for future cloud use — not required for local capture). */
  apiKey?: string;
  /** Propagate a parent trace context for multi-agent stitching. */
  parentContext?: TraceContext;
}

export interface RunOptions {
  parentRunId?: string;
}

// ── Pricing ─────────────────────────────────────────────────────────────────

const PRICE_TABLE: Record<string, [number, number]> = {
  // Anthropic  (input $/M, output $/M)
  'claude-opus-4':      [15.00, 75.00],
  'claude-sonnet-4':    [ 3.00, 15.00],
  'claude-3-5-sonnet':  [ 3.00, 15.00],
  'claude-3-5-haiku':   [ 0.80,  4.00],
  'claude-3-opus':      [15.00, 75.00],
  'claude-3-sonnet':    [ 3.00, 15.00],
  'claude-3-haiku':     [ 0.25,  1.25],
  // OpenAI
  'gpt-4o-mini':        [ 0.15,  0.60],
  'gpt-4o':             [ 2.50, 10.00],
  'gpt-4.1-nano':       [ 0.10,  0.40],
  'gpt-4.1-mini':       [ 0.40,  1.60],
  'gpt-4.1':            [ 2.00,  8.00],
  'gpt-4-turbo':        [10.00, 30.00],
  'gpt-4':              [30.00, 60.00],
  'gpt-3.5-turbo':      [ 0.50,  1.50],
  'o1-mini':            [ 3.00, 12.00],
  'o1':                 [15.00, 60.00],
  'o3-mini':            [ 1.10,  4.40],
  'o3':                 [10.00, 40.00],
};

function computeCostUsd(
  model: string | undefined,
  usage: Record<string, number> | undefined,
): number | null {
  if (!model || !usage || !['input_tokens', 'prompt_tokens', 'output_tokens', 'completion_tokens'].some(key => usage[key] != null)) return null;
  const m = model.toLowerCase().replace(/-(?:\d{4}-\d{2}-\d{2}|\d{8}|latest)$/, '');
  if (!Object.prototype.hasOwnProperty.call(PRICE_TABLE, m)) return null;
  const [inPrice, outPrice] = PRICE_TABLE[m];
  const count = (value: unknown): number => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0;
  const inputTok = count(usage.input_tokens ?? usage.prompt_tokens);
  const outputTok = count(usage.output_tokens ?? usage.completion_tokens);
  return Math.round((inputTok * inPrice + outputTok * outPrice) / 1_000_000 * 1e8) / 1e8;
}

// ── Internal state ───────────────────────────────────────────────────────────

const storage = new AsyncLocalStorage<Run>();
const RUNS_DIR = path.join('.agentlens', 'runs');

const _cfg = {
  initialized: false,
  patchedAnthropic: false,
  patchedOpenAI: false,
  parentRunId: undefined as string | undefined,
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function nowIso(): string {
  return new Date().toISOString();
}

function newUuid(): string {
  return crypto.randomUUID();
}

function toJsonable(value: unknown, depth = 0): unknown {
  if (depth > 30) return "[depth limit]";
  if (value === null || value === undefined) return value;
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value;
  if (Array.isArray(value)) return value.map(v => toJsonable(v, depth + 1));
  if (value instanceof Error) return { message: value.message, name: value.name };
  if (typeof value === 'object') {
    if (typeof (value as { toJSON?: () => unknown }).toJSON === 'function') {
      return toJsonable((value as { toJSON: () => unknown }).toJSON(), depth + 1);
    }
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as object)) out[k] = toJsonable(v, depth + 1);
    return out;
  }
  return String(value);
}

function appendSpan(spanData: {type: Span['type']; ts: string; [key: string]: unknown}): Span {
  const r = storage.getStore();
  if (!r) {
    // No active run — orphan span (best-effort, not persisted)
    return { id: newUuid(), run_id: 'orphan', ...spanData } as Span;
  }
  const id = newUuid();
  const span: Span = { ...spanData, id, span_id: id, original_index: r.spans.length + 1, run_id: r.run_id } as Span;
  r.spans.push(span);
  return span;
}

function saveRun(runData: Run): void {
  let temporary: string | undefined;
  try {
    fs.mkdirSync(RUNS_DIR, { recursive: true });
    const filePath = path.join(RUNS_DIR, runData.run_id + '.json');
    temporary = filePath + '.' + newUuid() + '.tmp';
    const fd = fs.openSync(temporary, 'wx', 0o600);
    try {
      fs.writeFileSync(fd, JSON.stringify(runData, null, 2), 'utf8');
      fs.fsyncSync(fd);
    } finally { fs.closeSync(fd); }
    fs.renameSync(temporary, filePath);
  } catch {
    process.emitWarning('Trace persistence failed; agent result is unchanged.');
  } finally {
    try {
      if (temporary && fs.existsSync(temporary)) fs.unlinkSync(temporary);
    } catch {
      process.emitWarning('Trace temporary-file cleanup failed.');
    }
  }
}

function safeError(error: unknown): string {
  const data = error as {status?: unknown};
  const status = data?.status;
  const message = String(error);
  // Node has no PII engine. Fail closed on credential-bearing exceptions rather
  // than partially masking provider text and accidentally retaining a key hint.
  if (status === 401 || status === 403 || /sk-|bearer|authorization|credentials?|password|secret|api[ _-]*key|(?:access|session|auth)[ _-]*token|(?:^|[\W_])token(?:["'\s]*[:=]|[ _-]*(?:hint|prefix|suffix|last4))|key[ _-]*(?:hint|prefix|suffix|ending|ends|starts|starting|begins)/i.test(message)) {
    const http = typeof status === 'number' && Number.isInteger(status) && status >= 100 && status <= 599 ? `HTTP ${status}: ` : '';
    return http + 'Request failed. Credential-bearing error details omitted. [REDACTED]';
  }
  return message;
}

function errorMetadata(error: unknown): Record<string, unknown> {
  const data = error as {status?: unknown; request_id?: unknown; requestID?: unknown};
  const name = error instanceof Error ? error.constructor.name : 'Error';
  const known = ['Error', 'APIError', 'AuthenticationError', 'PermissionDeniedError', 'BadRequestError', 'RateLimitError', 'NotFoundError'];
  const metadata: Record<string, unknown> = {error_type: known.includes(name) ? name : 'Error'};
  if (typeof data?.status === 'number' && Number.isInteger(data.status) && data.status >= 100 && data.status <= 599) metadata.status_code = data.status;
  const requestId = data?.request_id ?? data?.requestID;
  if (typeof requestId === 'string' && /^req_[A-Za-z0-9_-]{1,200}$/.test(requestId) && safeError(requestId) === requestId) metadata.request_id = requestId;
  return metadata;
}

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * Initialize AgentLens. Patches Anthropic and OpenAI SDKs if installed.
 * Call once at process start before creating any LLM clients.
 */
export function init(options: InitOptions = {}): void {
  if (options.parentContext?.parent_run_id) {
    _cfg.parentRunId = options.parentContext.parent_run_id;
  }
  if (!_cfg.initialized) {
    patchAnthropic();
    patchOpenAI();
    _cfg.initialized = true;
    if (!_cfg.patchedAnthropic && !_cfg.patchedOpenAI) process.emitWarning("No supported provider SDK installed.");
  }
}

/**
 * Run an async function within a named AgentLens run.
 * All spans created inside fn() are automatically attached to this run and saved.
 *
 * @example
 * await run('customer-support-agent', async () => {
 *   const client = new Anthropic();
 *   return client.messages.create({ ... }); // auto-captured
 * });
 */
export async function run<T>(
  name: string,
  fn: () => Promise<T>,
  options: RunOptions = {},
): Promise<T> {
  const runData: Run = {
    run_id: newUuid(),
    name,
    started_at: nowIso(),
    ended_at: null,
    status: 'running',
    spans: [],
    ...(options.parentRunId ?? _cfg.parentRunId
      ? { parent_run_id: options.parentRunId ?? _cfg.parentRunId }
      : {}),
  };

  return storage.run(runData, async () => {
    try {
      const result = await fn();
      if (runData.status === 'running') runData.status = 'success';
      return result;
    } catch (err) {
      runData.status = err instanceof Error && err.name === 'AbortError' ? 'cancelled' : 'error';
      runData.error = safeError(err);
      appendSpan({ type: 'error', ts: nowIso(), error: safeError(err), ...errorMetadata(err), context: { function: name } });
      throw err;
    } finally {
      runData.ended_at = nowIso();
      // Promote to error if any error spans exist
      if (runData.status === 'success' && runData.spans.some(s => s.type === 'error' || s.error)) {
        runData.status = 'error';
      }
      if (runData.status === 'success' && runData.spans.some(s => s.type === 'tool_call' && s.completed !== true)) {
        runData.status = 'partial';
      }
      saveRun(runData);
    }
  });
}

/**
 * Get the current run's trace context for multi-agent propagation.
 * Pass the returned object to init() in the child process / service.
 *
 * @example
 * const ctx = getTraceContext();
 * // In the child agent:
 * init({ parentContext: ctx });
 */
export function getTraceContext(): TraceContext | null {
  const r = storage.getStore();
  if (!r) return null;
  return { parent_run_id: r.run_id };
}

/**
 * Manually record a tool result span.
 * Use this when you call a tool outside the auto-captured LLM response loop.
 */
export function recordToolResult(options: {
  toolName: string;
  input?: unknown;
  output?: unknown;
  toolUseId?: string;
}): void {
  const r = storage.getStore();
  const existing = options.toolUseId ? r?.spans.find(s => s.type === 'tool_call' && s.tool_use_id === options.toolUseId) : undefined;
  const fields = {
    type: 'tool_call' as const, ts: nowIso(), tool_name: options.toolName,
    input: toJsonable(options.input) ?? null, output: toJsonable(options.output) ?? null,
    tool_use_id: options.toolUseId ?? null, completed: true,
  };
  if (existing) Object.assign(existing, fields);
  else appendSpan(fields);
}

/**
 * Capture a snapshot of agent memory / state at the current point in time.
 * Enables the Memory State Snapshots view in the timeline UI.
 *
 * @example
 * recordMemorySnapshot('after_lookup', { customer: 'alex', status: 'active' });
 */
export function recordMemorySnapshot(label: string, state: Record<string, unknown>): void {
  appendSpan({
    type: 'memory_snapshot',
    ts: nowIso(),
    label,
    state: toJsonable(state),
  });
}

// Resource methods are patched without replacing client constructors.
type RecordValue = Record<string, any>;

function captureTools(response: RecordValue, provider: string): void {
  const calls = provider === 'anthropic'
    ? (response.content ?? []).filter((b: RecordValue) => b.type === 'tool_use')
    : (response.choices ?? []).flatMap((c: RecordValue) => c.message?.tool_calls ?? []);
  for (const call of calls) {
    const id = call.id;
    if (id && storage.getStore()?.spans.some(s => s.type === 'tool_call' && s.tool_use_id === id)) continue;
    let input = call.input ?? call.function?.arguments;
    if (typeof input === 'string') {
      try { input = JSON.parse(input); } catch { /* Preserve invalid provider arguments as evidence. */ }
    }
    appendSpan({ type: 'tool_call', ts: nowIso(), tool_use_id: id,
      tool_name: call.name ?? call.function?.name, input, output: null, completed: false });
  }
}

function captureResults(messages: RecordValue[]): void {
  for (const message of messages) {
    const blocks = message.role === 'tool'
      ? [{ tool_use_id: message.tool_call_id, content: message.content }]
      : Array.isArray(message.content) ? message.content.filter((b: RecordValue) => b.type === 'tool_result') : [];
    for (const block of blocks) {
      const span = storage.getStore()?.spans.find(s => s.type === 'tool_call' && s.tool_use_id === block.tool_use_id);
      if (!span) continue;
      recordToolResult({toolName: String(span.tool_name), input: span.input,
        output: block.content, toolUseId: block.tool_use_id});
      if (block.is_error) span.error = block.content;
    }
  }
}

function patchResource(moduleName: string, className: string, provider: string): boolean {
  let resource: any;
  try { resource = require(moduleName)[className]; }
  catch { return false; }
  const original = resource.prototype.create;
  if (original.__agentlens) return true;
  function create(this: unknown, params: RecordValue, ...options: unknown[]) {
    const active = storage.getStore();
    const started = Date.now();
    if (!active) return original.call(this, params, ...options);
    captureResults(params.messages ?? []);
    const request = toJsonable(params) as RecordValue;
    const finish = (response: RecordValue | null, error?: unknown) => storage.run(active, () => {
      appendSpan({type: 'llm_call', provider, ts: nowIso(), model: request.model,
        input_messages: request.messages ?? [], tools: request.tools ?? [], system: request.system,
        latency_ms: Date.now() - started, response_content: toJsonable(provider === 'anthropic' ? response?.content : response),
        usage: toJsonable(response?.usage), stop_reason: response?.stop_reason ?? response?.choices?.[0]?.finish_reason,
        status: error ? 'error' : 'completed', error: error ? safeError(error) : null,
        ...(error ? errorMetadata(error) : {}),
        cost_usd: computeCostUsd(request.model, response?.usage)});
      if (response) captureTools(response, provider);
      if (error) appendSpan({type: 'error', ts: nowIso(), error: safeError(error), ...errorMetadata(error), context: {provider, model: request.model}});
    });
    let promise: any;
    try { promise = original.call(this, params, ...options); }
    catch (error) { finish(null, error); throw error; }
    // Keep the SDK's original APIPromise, including withResponse/asResponse.
    promise.then((response: RecordValue) => {
      if (params.stream) {
        active.status = 'partial';
        process.emitWarning('Node streaming capture is not supported; use Python or non-streaming create.');
        return;
      }
      try { finish(response); } catch { process.emitWarning('Trace capture failed; provider result is unchanged.'); }
    }, (error: unknown) => { try { finish(null, error); } catch { process.emitWarning('Error trace capture failed.'); } });
    return promise;
  }
  (create as any).__agentlens = true;
  resource.prototype.create = create;
  return true;
}

function patchAnthropic(): void {
  _cfg.patchedAnthropic = patchResource('@anthropic-ai/sdk/resources/messages', 'Messages', 'anthropic');
}
function patchOpenAI(): void {
  _cfg.patchedOpenAI = patchResource('openai/resources/chat/completions', 'Completions', 'openai');
}
