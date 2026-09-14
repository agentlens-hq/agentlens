import asyncio
import json
import unittest
from unittest.mock import patch

import anthropic
import httpx
import openai

from agentlens_sdk import collector as c
from agentlens_sdk.streams import AsyncStream, Stream
from tests.test_provider_protocols import transport


def message():
    return {'id': 'm', 'type': 'message', 'role': 'assistant', 'model': 'test', 'content': [], 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 0}}


def anthropic_transport(request):
    events = [
        {'type': 'message_start', 'message': message()},
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'tool_use', 'id': 'ta', 'name': 'lookup', 'input': {}}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'input_json_delta', 'partial_json': '{"id":1}'}},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use', 'stop_sequence': None}, 'usage': {'output_tokens': 5}},
        {'type': 'message_stop'},
    ]
    if json.loads(request.content).get('stream'):
        data = ''.join('event: ' + e['type'] + '\ndata: ' + json.dumps(e) + '\n\n' for e in events)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=data)
    return httpx.Response(200, json=dict(message(), content=[{'type': 'text', 'text': 'done'}], stop_reason='end_turn'))


def responses_transport(request):
    result = {'id': 'resp_1', 'object': 'response', 'created_at': 1, 'status': 'completed', 'model': 'test', 'output': [{'id': 'fc1', 'type': 'function_call', 'call_id': 'rc1', 'name': 'lookup', 'arguments': '{"id":1}', 'status': 'completed'}], 'usage': {'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 3}}
    if json.loads(request.content).get('stream'):
        event = {'type': 'response.completed', 'sequence_number': 1, 'response': result}
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content='data: ' + json.dumps(event) + '\n\n')
    return httpx.Response(200, json=result)


class ProviderMatrix(unittest.TestCase):
    def setUp(self):
        self.token = c._current_run.set(c.start_run())
        c.init()

    def tearDown(self):
        c._current_run.reset(self.token)

    def test_anthropic_sync_stream_and_manager(self):
        with anthropic.Anthropic(api_key='test', http_client=httpx.Client(transport=httpx.MockTransport(anthropic_transport))) as client:
            chunks = list(client.with_options(timeout=1).messages.create(model='test', messages=[], system='goal', max_tokens=20, stream=True))
            self.assertEqual(len(chunks), 6)
            with client.messages.stream(model='test', messages=[], max_tokens=20) as stream:
                list(stream)
        spans = c.current_run()['spans']
        calls = [s for s in spans if s['type'] == 'llm_call']
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['system'], 'goal')
        self.assertTrue(all(s['status'] == 'completed' for s in calls))
        self.assertEqual(next(s for s in spans if s['type'] == 'tool_call')['input'], {'id': 1})

    def test_anthropic_async_normal_stream_manager(self):
        async def work():
            async with anthropic.AsyncAnthropic(api_key='test', http_client=httpx.AsyncClient(transport=httpx.MockTransport(anthropic_transport))) as client:
                await client.with_options(timeout=1).messages.create(model='test', messages=[], system='goal', max_tokens=20)
                stream = await client.messages.create(model='test', messages=[], max_tokens=20, stream=True)
                self.assertEqual(len([x async for x in stream]), 6)
                async with client.messages.stream(model='test', messages=[], max_tokens=20) as managed:
                    events = [x async for x in managed]
                    self.assertEqual(events[-1].type, 'message_stop')
                    self.assertTrue(any(x.type == 'input_json' for x in events))
        asyncio.run(work())
        calls = [s for s in c.current_run()['spans'] if s['type'] == 'llm_call']
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(s['status'] == 'completed' for s in calls))

    def test_responses_sync_context_and_results(self):
        with openai.OpenAI(api_key='test', http_client=httpx.Client(transport=httpx.MockTransport(responses_transport))) as client:
            client.responses.create(model='test', input='goal', instructions='original goal')
            client.responses.create(model='test', previous_response_id='resp_1', input=[{'type': 'function_call_output', 'call_id': 'rc1', 'output': 'found'}])
            list(client.responses.create(model='test', input='goal', stream=True))
        spans = c.current_run()['spans']
        calls = [s for s in spans if s['type'] == 'llm_call']
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]['instructions'], 'original goal')
        self.assertEqual(calls[1]['previous_response_id'], 'resp_1')
        self.assertEqual(next(s for s in spans if s['type'] == 'tool_call')['output'], 'found')

    def test_responses_async_and_stream(self):
        async def work():
            async with openai.AsyncOpenAI(api_key='test', http_client=httpx.AsyncClient(transport=httpx.MockTransport(responses_transport))) as client:
                await client.responses.create(model='test', input='goal', instructions='goal')
                stream = await client.responses.create(model='test', input='goal', stream=True)
                self.assertEqual(len([x async for x in stream]), 1)
        asyncio.run(work())
        self.assertEqual(len([s for s in c.current_run()['spans'] if s['type'] == 'llm_call']), 2)

    def test_async_normal_and_provider_errors(self):
        async def work():
            async with openai.AsyncOpenAI(api_key='test', max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))) as client:
                await client.chat.completions.create(model='test', messages=[])
            async with openai.AsyncOpenAI(api_key='test', max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={'error': {'message': 'invalid key'}})))) as client:
                with self.assertRaises(openai.AuthenticationError):
                    await client.chat.completions.create(model='test', messages=[])
        asyncio.run(work())
        self.assertTrue(any(s['type'] == 'error' for s in c.current_run()['spans']))

    def test_stream_transport_error_and_cancel_preserved(self):
        def broken():
            yield {'choices': []}
            raise OSError('transport interrupted')
        finished = []
        wrapped = Stream(broken(), 'openai', 'chat', lambda x: x, lambda *args: finished.append(args))
        with self.assertRaises(OSError):
            list(wrapped)
        wrapped.close()
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], 'error')
        async def cancelled():
            yield {'choices': []}
            raise asyncio.CancelledError()
        async def work():
            stream = AsyncStream(cancelled(), 'openai', 'chat', lambda x: x, lambda *args: finished.append(args))
            with self.assertRaises(asyncio.CancelledError):
                async for _ in stream:
                    pass
            await stream.close()
        asyncio.run(work())
        self.assertEqual(finished[-1][1], 'cancelled')
        self.assertEqual(len(finished), 2)

    def test_parallel_run_attribution(self):
        saved = []
        @c.run('parallel')
        async def worker(label):
            async with openai.AsyncOpenAI(api_key='test', http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))) as client:
                await asyncio.sleep(0)
                await client.chat.completions.create(model='test', messages=[{'role': 'user', 'content': label}])
        async def work():
            await asyncio.gather(worker('one'), worker('two'))
        with patch.object(c, 'save_run', side_effect=lambda **kwargs: saved.append(kwargs['run'])):
            asyncio.run(work())
        self.assertEqual(len({r['run_id'] for r in saved}), 2)
        for run in saved:
            self.assertEqual({s['run_id'] for s in run['spans']}, {run['run_id']})
            self.assertEqual(len([s for s in run['spans'] if s['type'] == 'llm_call']), 1)
