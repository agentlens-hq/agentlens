"""Controlled boundary regressions, not live-provider or real-user validation."""
import asyncio
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import anthropic
import httpx
import openai

import agentlens
from agentlens_core.privacy import anonymize
from agentlens_core.trace import read_run
from agentlens_engine.diagnose import diagnose_run
from agentlens_engine.preprocess import preprocess_run
from agentlens_sdk import collector as c


def chat(tools=None):
    message = {'role': 'assistant', 'content': 'Completed local request.'}
    if tools:
        message['tool_calls'] = tools
    return {'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': 'synthetic', 'choices': [{'index': 0, 'message': message,
                                             'finish_reason': 'tool_calls' if tools else 'stop'}],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}}


def tool_call(name, call_id, arguments):
    return {'id': call_id, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments)}}


def tool_definition(name):
    return {'type': 'function', 'function': {'name': name, 'description': 'Lookup customer',
            'parameters': {'type': 'object', 'properties': {'customer_id': {'type': 'string'}},
                           'required': ['customer_id'], 'additionalProperties': False}}}


class InfrastructureBoundaries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self._enter(patch.object(c, 'RUNS_DIR', self.directory))
        self._enter(patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')))
        self._enter(patch('socket.create_connection', side_effect=AssertionError('Network forbidden')))
        self._enter(patch('agentlens_engine.diagnose._diagnose_with_llm', side_effect=AssertionError('Remote diagnosis forbidden')))
        self._enter(patch('agentlens_core.privacy._name_model', return_value=None))
        token = c._current_run.set(None)
        self.addCleanup(c._current_run.reset, token)
        c.init()

    def _enter(self, manager):
        result = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        return result

    def saved(self, name):
        return next(read_run(path) for path in self.directory.glob('*.json')
                    if json.loads(path.read_text())['name'] == name)

    def assert_unknown(self, run):
        result = diagnose_run(run)
        self.assertEqual(result['root_cause_category'], 'unknown', result)
        self.assertEqual(result['failed_at_step'], 0, result)
        self.assertLess(result['confidence'], .6, result)
        return result

    def inspect(self, run):
        output = io.StringIO()
        with patch.object(agentlens, '_load_run_or_report', return_value=run), contextlib.redirect_stdout(output):
            agentlens._print_run_detail(run['run_id'])
        self.assertTrue(output.getvalue())
        self.assertNotIn('Traceback', output.getvalue())
        return output.getvalue()

    def provider_run(self, provider, case, recover=False):
        name = f'{provider}-{case}-{recover}'
        requests = []

        def handler(request):
            requests.append(request)
            if recover and len(requests) > 1:
                return httpx.Response(200, json=chat())
            if case == 'timeout':
                raise httpx.ReadTimeout('Synthetic request timeout', request=request)
            if case == 'connection':
                raise httpx.ConnectError('Synthetic connection reset', request=request)
            if case == 'malformed':
                return httpx.Response(200, json={'unexpected': 'not a provider response'})
            return httpx.Response(case, headers={'x-request-id': 'req_synthetic_boundary', 'retry-after': '2'},
                                  json={'type': 'error', 'error': {'type': 'api_error',
                                        'message': 'Synthetic upstream failure. Retry after 2 seconds. Bearer FAKE_BOUNDARY_SECRET'}})

        @c.run(name)
        def work():
            sdk = openai.OpenAI if provider == 'openai' else anthropic.Anthropic
            with sdk(api_key='synthetic-not-a-credential', max_retries=0,
                     http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
                def call():
                    if provider == 'openai':
                        return client.chat.completions.create(model='synthetic', messages=[{'role': 'user', 'content': 'Find customer 382.'}])
                    return client.messages.create(model='synthetic', max_tokens=8, messages=[{'role': 'user', 'content': 'Find customer 382.'}])
                try:
                    call()
                except Exception:
                    if not recover:
                        raise
                    call()

        try:
            work()
        except (openai.APIError, anthropic.APIError):
            pass
        run = self.saved(name)
        self.assertNotIn('FAKE_BOUNDARY_SECRET', json.dumps(run))
        self.assert_unknown(run)
        self.inspect(run)
        for span in run['spans']:
            if span.get('latency_ms') is not None:
                self.assertGreaterEqual(span['latency_ms'], 0)
                self.assertLess(span['latency_ms'], 10000)
        return run

    def test_provider_error_matrix(self):
        for provider in ('openai', 'anthropic'):
            for case in (401, 403, 429, 500, 502, 503, 'timeout', 'connection'):
                with self.subTest(provider=provider, case=case):
                    run = self.provider_run(provider, case)
                    self.assertEqual(run['status'], 'error')
                    errors = [s for s in run['spans'] if s['type'] == 'error']
                    self.assertTrue(errors)
                    self.assertTrue(errors[0]['error_type'])
                    if isinstance(case, int):
                        self.assertEqual(errors[0]['status_code'], case)
                        if case == 429:
                            self.assertIn('Retry after 2 seconds', errors[0]['error'])

    def test_malformed_provider_response_not_success(self):
        for provider in ('openai', 'anthropic'):
            with self.subTest(provider=provider):
                run = self.provider_run(provider, 'malformed')
                self.assertNotEqual(run['status'], 'success')
                self.assertTrue(any(s.get('error') for s in run['spans']))

    def test_provider_recovery_abstains(self):
        for case in (429, 'timeout'):
            with self.subTest(case=case):
                run = self.provider_run('openai', case, recover=True)
                calls = [s for s in run['spans'] if s['type'] == 'llm_call']
                self.assertEqual([s['status'] for s in calls], ['error', 'completed'])
                self.assertIn('Completed local request', json.dumps(calls[-1]))

    def test_responses_failed_and_incomplete_not_success(self):
        for status in ('failed', 'incomplete'):
            with self.subTest(status=status):
                @c.run(status)
                def work():
                    body = {'id': 'synthetic', 'object': 'response', 'created_at': 1,
                            'model': 'synthetic', 'output': [], 'status': status,
                            'error': {'code': 'server_error', 'message': 'Synthetic provider failure'} if status == 'failed' else None}
                    with openai.OpenAI(api_key='synthetic', max_retries=0,
                                       http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))) as client:
                        client.responses.create(model='synthetic', input='Find customer 382.')
                work()
                run = self.saved(status)
                self.assert_unknown(run)
                self.assertEqual(run['status'], 'error' if status == 'failed' else 'partial')

    def test_malformed_response_fields_not_success(self):
        cases = [
            ('openai', {'choices': [None]}),
            ('openai', {'choices': [{'message': {'tool_calls': [{'id': 'broken', 'function': None}]}}]}),
            ('openai', dict(chat(), usage='not usage')),
            ('anthropic', {'content': [None]}),
        ]
        for index, (provider, body) in enumerate(cases):
            with self.subTest(index=index):
                @c.run(f'malformed-fields-{index}')
                def work():
                    c._capture_sync(lambda: body, {'model': 'synthetic', 'messages': []}, provider, 'chat' if provider == 'openai' else 'messages')
                work()
                run = self.saved(f'malformed-fields-{index}')
                self.assertEqual(run['status'], 'error')
                self.assertTrue(any(s['type'] == 'error' for s in run['spans']))
                self.assert_unknown(run)

    def test_async_cancellation_and_caught_cancellation(self):
        for caught in (False, True):
            with self.subTest(caught=caught):
                ready = None
                async def handler(request):
                    ready.set()
                    await asyncio.Event().wait()

                @c.run(f'cancel-{caught}')
                async def worker():
                    async with openai.AsyncOpenAI(api_key='synthetic', max_retries=0,
                                                  http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
                        try:
                            await client.chat.completions.create(model='synthetic', messages=[])
                        except asyncio.CancelledError:
                            if not caught:
                                raise

                async def work():
                    nonlocal ready
                    ready = asyncio.Event()
                    task = asyncio.create_task(worker())
                    await ready.wait()
                    task.cancel()
                    if caught:
                        await task
                    else:
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                asyncio.run(work())
                run = self.saved(f'cancel-{caught}')
                self.assertNotEqual(run['status'], 'success')
                self.assertEqual(run['spans'][0]['status'], 'cancelled')
                self.assert_unknown(run)

    def test_stream_cancellation_saved(self):
        ready = None
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices":[{"index":0,"delta":{"content":"Partial answer"},"finish_reason":null}]}\n\n'
                ready.set()
                await asyncio.Event().wait()

        @c.run('stream-cancel')
        async def worker():
            async with openai.AsyncOpenAI(api_key='synthetic', max_retries=0,
                                          http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Body())))) as client:
                stream = await client.chat.completions.create(model='synthetic', messages=[], stream=True)
                async with stream:
                    async for _ in stream:
                        pass

        async def work():
            nonlocal ready
            ready = asyncio.Event()
            task = asyncio.create_task(worker())
            await ready.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(work())
        run = self.saved('stream-cancel')
        self.assertEqual(run['status'], 'cancelled')
        self.assertEqual(run['spans'][0]['status'], 'cancelled')
        self.assertIn('Partial answer', json.dumps(run))
        self.assert_unknown(run)

    def tool_run(self, name, arguments, output):
        class DatabaseConnectionTimeout(Exception):
            pass

        @c.run(name)
        def worker():
            calls = [tool_call(name, 'call_synthetic', arguments)]
            with openai.OpenAI(api_key='synthetic', max_retries=0,
                               http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=chat(calls))))) as client:
                client.chat.completions.create(model='synthetic', messages=[{'role': 'user', 'content': 'Find customer 382.'}], tools=[tool_definition(name)])
            try:
                if output == {'error': 'DatabaseConnectionTimeout'}:
                    raise DatabaseConnectionTimeout('DatabaseConnectionTimeout')
            except DatabaseConnectionTimeout:
                c.record_tool_result(name, output, tool_use_id='call_synthetic')
                raise
            c.record_tool_result(name, output, tool_use_id='call_synthetic')
        try:
            worker()
        except DatabaseConnectionTimeout:
            pass
        return self.saved(name)

    def test_correct_tool_implementation_and_permission_failure(self):
        for name, error in (('query_customer_database', 'DatabaseConnectionTimeout'), ('issue_refund', 'PermissionDenied: insufficient_scope')):
            with self.subTest(name=name):
                run = self.tool_run(name, {'customer_id': '382'}, {'error': error})
                self.assert_unknown(run)
                tool = next(s for s in run['spans'] if s['type'] == 'tool_call')
                self.assertEqual(tool['tool_name'], name)
                self.assertEqual(tool['input'], {'customer_id': '382'})
                self.assertEqual(tool['output'], {'error': error})
                self.assertIn(error, self.inspect(run))

    def test_malformed_arguments_schema_finding(self):
        run = self.tool_run('query_customer_database', {'customer_id': '382', 'admin_override': True}, {'error': 'Unexpected argument admin_override'})
        result = self.assert_unknown(run)
        findings = result['hallucinations']
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['type'], 'invented_param')
        self.assertEqual(findings[0]['step'], 2)
        self.assertIn('admin_override', findings[0]['detail'])

    def test_null_dataflow_and_unrelated_control(self):
        for related in (True, False):
            with self.subTest(related=related):
                name = f'null-{related}'
                @c.run(name)
                def work():
                    c.record_tool_result('find_customer', {'customer_id': None}, input={'name': 'Example'}, tool_use_id='a')
                    c.record_tool_result('load_orders', {'error': 'customer_id is null'} if related else {'error': 'DatabaseConnectionTimeout'},
                                         input={'customer_id': None if related else '991'}, tool_use_id='b')
                work()
                result = diagnose_run(self.saved(name))
                self.assertEqual(result['root_cause_category'], 'cascade' if related else 'unknown', result)
                self.assertEqual(result['failed_at_step'], 1 if related else 0)

    def test_parallel_tools_and_concurrent_runs(self):
        async def batch(index):
            barrier = asyncio.Event()
            arrivals = 0
            async def handler(request):
                nonlocal arrivals
                body = json.loads(request.content)
                label = body['messages'][0]['content']
                if body['messages'][-1]['role'] == 'tool':
                    return httpx.Response(200, json=chat())
                arrivals += 1
                if arrivals == 2:
                    barrier.set()
                await barrier.wait()
                return httpx.Response(200, json=chat([
                    tool_call('get_customer_profile', 'shared-profile-id', {'customer_id': label}),
                    tool_call('get_order_status', 'shared-order-id', {'order_id': label + '-991'})]))

            @c.run('parallel')
            async def worker(label):
                async with openai.AsyncOpenAI(api_key='synthetic', max_retries=0,
                                              http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
                    messages = [{'role': 'user', 'content': label}]
                    response = await client.chat.completions.create(model='synthetic', messages=messages)
                    async def result(call):
                        await asyncio.sleep(0)
                        failed = label.startswith('A-') and call.function.name == 'get_order_status'
                        output = {'error': 'DatabaseConnectionTimeout', 'owner': label} if failed else {'owner': label, 'result': 'found'}
                        c.record_tool_result(call.function.name, output, tool_use_id=call.id)
                        return {'role': 'tool', 'tool_call_id': call.id, 'content': json.dumps(output)}
                    results = await asyncio.gather(*(result(call) for call in reversed(response.choices[0].message.tool_calls)))
                    await client.chat.completions.create(model='synthetic', messages=messages + results)
                return c.current_run()['run_id'], label
            return await asyncio.gather(worker(f'A-{index}'), worker(f'B-{index}'))

        async def work():
            results = []
            for index in range(10):
                results.extend(await batch(index))
            return results
        pairs = asyncio.run(work())
        self.assertEqual(len({run_id for run_id, _ in pairs}), 20)
        for run_id, label in pairs:
            run = read_run(self.directory / (run_id + '.json'))
            self.assertFalse(run.get('parent_run_id'))
            self.assertEqual(run['status'], 'error' if label.startswith('A-') else 'success')
            self.assertEqual({s['run_id'] for s in run['spans']}, {run_id})
            calls = [s for s in run['spans'] if s['type'] == 'llm_call']
            self.assertEqual(len(calls), 2)
            self.assertEqual({s['input_messages'][0]['content'] for s in calls}, {label})
            tools = [s for s in run['spans'] if s['type'] == 'tool_call']
            self.assertEqual(len(tools), 2)
            for tool in tools:
                self.assertEqual(tool['parent_span_id'], calls[0]['span_id'])
                self.assertEqual(tool['output']['owner'], label)
                self.assertEqual(tool['input'], {'customer_id': label} if tool['tool_name'] == 'get_customer_profile' else {'order_id': label + '-991'})
                self.assertEqual('error' in tool['output'], label.startswith('A-') and tool['tool_name'] == 'get_order_status')
            self.assert_unknown(run)

    def test_large_and_weird_data(self):
        values = ['Unicode: \u65e5\u672c\u8a9e \U0001f680', 'a\nb\t"\\<>', None, '', [],
                  {'nested': {'value': [None, 7]}}, b'\x00\xff', 'x' * (1024 * 1024)]
        @c.run('weird')
        def work():
            for index, value in enumerate(values):
                c.record_tool_result('lookup', value, input={'index': index}, tool_use_id=str(index))
            c.capture_error('DatabaseConnectionTimeout', context={'operation': 'export'})
        work()
        run = self.saved('weird')
        self.assertEqual(run['spans'][-2]['output'], values[-1])
        self.assertEqual(run['spans'][-3]['output'], '<bytes>')
        self.assertLess(len(json.dumps(preprocess_run(run['spans'], run))), 25000)
        self.assertIn('DatabaseConnectionTimeout', json.dumps(preprocess_run(run['spans'], run)))
        self.assertLess(len(self.inspect(run)), 25000)
        self.assert_unknown(run)
        self.assertTrue(anonymize(run))

    def test_long_unbroken_text_redaction_is_bounded(self):
        # Bound the regression externally: a regex stall must fail, not hang CI.
        code = (
            "from agentlens_core.privacy import redact_credentials, anonymize, residual; "
            "import agentlens_core.privacy as p; p._name_model=lambda:None; "
            "text='x'*1048576; assert redact_credentials(text)==text; "
            "assert anonymize(text)==text; assert residual(text)==[]"
        )
        subprocess.run([sys.executable, '-c', code], check=True, capture_output=True, timeout=15)


if __name__ == '__main__':
    unittest.main()
