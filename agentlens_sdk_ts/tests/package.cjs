const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {OpenAI} = require('openai');
const {Anthropic} = require('@anthropic-ai/sdk');
const lens = require('..');
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'agentlens-node-'));
process.chdir(directory);
lens.init();

function runs() {
  return fs.readdirSync('.agentlens/runs').map(file => JSON.parse(fs.readFileSync(path.join('.agentlens/runs', file))));
}
test('exports and declarations resolve from built package', async () => {
  const pkg = require('../package.json');
  for (const target of Object.values(pkg.exports['.'])) assert.ok(fs.existsSync(path.join(__dirname, '..', target)));
  const esm = await import(pathToFileURL(path.join(__dirname, '../dist/index.js')).href);
  assert.equal(typeof esm.init, 'function');
});

test('OpenAI forwards request options, captures calls/results, preserves aliases and APIPromise', async () => {
  const requests = [];
  class Custom extends OpenAI {}
  const client = new Custom({apiKey: 'test', baseURL: 'https://local.invalid', fetch: async (url, init) => {
    requests.push({url: String(url), init});
    return new Response(JSON.stringify({id: 'r', object: 'chat.completion', created: 1, model: 'test', choices: [{index: 0, finish_reason: 'tool_calls', message: {role: 'assistant', content: null, tool_calls: [{id: 't1', type: 'function', function: {name: 'lookup', arguments: '{"id":1}'}}]}}], usage: {prompt_tokens: 1, completion_tokens: 2}}), {headers: {'content-type': 'application/json'}});
  }});
  await lens.run('openai', async () => {
    const promise = client.chat.completions.create({model: 'test', messages: []}, {headers: {'x-custom': 'forwarded'}});
    assert.equal(typeof promise.withResponse, 'function');
    await promise;
    await client.chat.completions.create({model: 'test', messages: [{role: 'tool', tool_call_id: 't1', content: 'found'}]});
    lens.recordToolResult({toolName: 'lookup', toolUseId: 't1', input: {id: 1}, output: null});
    lens.recordToolResult({toolName: 'lookup', toolUseId: 't1', input: {id: 1}, output: null});
  });
  assert.ok(requests[0].url.startsWith('https://local.invalid'));
  assert.equal(new Headers(requests[0].init.headers).get('x-custom'), 'forwarded');
  const run = runs().find(r => r.name === 'openai');
  const tools = run.spans.filter(s => s.type === 'tool_call');
  assert.equal(tools.length, 1);
  assert.equal(tools[0].completed, true);
  assert.equal(tools[0].output, null);
  assert.equal(run.spans.filter(s => s.type === 'llm_call').length, 2);
});

test('Anthropic preserves system context and automatic tool selection', async () => {
  const client = new Anthropic({apiKey: 'test', fetch: async () => new Response(JSON.stringify({id: 'm', type: 'message', role: 'assistant', model: 'test', content: [{type: 'tool_use', id: 'a1', name: 'lookup', input: {id: 1}}], stop_reason: 'tool_use', usage: {input_tokens: 1, output_tokens: 2}}), {headers: {'content-type': 'application/json'}})});
  await lens.run('anthropic', async () => {
    await client.messages.create({model: 'test', max_tokens: 20, system: 'goal', messages: []});
  });
  const run = runs().find(r => r.name === 'anthropic');
  assert.equal(run.spans[0].system, 'goal');
  assert.equal(run.spans[1].tool_name, 'lookup');
  assert.equal(run.status, 'partial');
});

test('cost distinguishes unknown usage and model versions without double counting aliases', async () => {
  for (const [name, model, usage, expected] of [
    ['aliases', 'gpt-4o-mini', {input_tokens: 10, prompt_tokens: 10, output_tokens: 20, completion_tokens: 20}, 0.0000135],
    ['no_usage', 'gpt-4o-mini', {}, null],
    ['unknown_model', 'gpt-4o-mini-next', {prompt_tokens: 10}, null],
    ['zero', 'gpt-4o-mini', {prompt_tokens: 0, completion_tokens: 0}, 0],
  ]) {
    const client = new OpenAI({apiKey: 'test', fetch: async () => new Response(JSON.stringify({id: name, object: 'chat.completion', created: 1, model, choices: [{index: 0, finish_reason: 'stop', message: {role: 'assistant', content: 'done'}}], usage}), {headers: {'content-type': 'application/json'}})});
    await lens.run(name, async () => { await client.chat.completions.create({model, messages: []}); });
    assert.equal(runs().find(r => r.name === name).spans[0].cost_usd, expected);
  }
});

test('persistence cleanup failure does not replace the application result', async () => {
  const rename = fs.renameSync;
  const unlink = fs.unlinkSync;
  const warn = process.emitWarning;
  const warnings = [];
  try {
    fs.renameSync = () => { throw new Error('rename denied'); };
    fs.unlinkSync = () => { throw new Error('cleanup denied'); };
    process.emitWarning = message => warnings.push(message);
    assert.equal(await lens.run('save_failure', async () => 123), 123);
    assert.equal(warnings.length, 2);
  } finally {
    fs.renameSync = rename;
    fs.unlinkSync = unlink;
    process.emitWarning = warn;
  }
});

test('parallel runs remain isolated and cancellation is retained', async () => {
  await Promise.all(['one', 'two'].map(name => lens.run(name, async () => { await Promise.resolve(); lens.recordMemorySnapshot(name, {value: name}); })));
  const one = runs().find(r => r.name === 'one');
  const two = runs().find(r => r.name === 'two');
  assert.notEqual(one.run_id, two.run_id);
  assert.equal(one.spans[0].run_id, one.run_id);
  await assert.rejects(lens.run('cancelled', async () => { const e = new Error('aborted'); e.name = 'AbortError'; throw e; }));
  assert.equal(runs().find(r => r.name === 'cancelled').status, 'cancelled');
});
