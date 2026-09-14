import asyncio
import json
import unittest

import anthropic
import httpx
import openai

from agentlens_sdk import collector as c


def chat_response():
    return {'id': 'a', 'object': 'chat.completion', 'created': 1, 'model': 'gpt-4o-mini', 'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_a', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{"id":1}'}}]}}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 3}}


def transport(request):
    body = json.loads(request.content)
    if body.get('stream'):
        events = [{'id': 'a', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'gpt-4o-mini', 'choices': [{'index': 0, 'delta': {'content': 'hello'}, 'finish_reason': None}]}, {'id': 'a', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'gpt-4o-mini', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}]
        content = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events) + 'data: [DONE]\n\n'
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=content)
    return httpx.Response(200, json=chat_response())


class ProviderProtocolTests(unittest.TestCase):
    def setUp(self):
        self.original_alias = openai.OpenAI
        self.token = c._current_run.set(c.start_run())
        c.init()

    def tearDown(self):
        c._current_run.reset(self.token)

    def test_sync_alias_context_clone_and_tools(self):
        class Custom(self.original_alias):
            pass
        with Custom(api_key='test', base_url='https://local.invalid', http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
            clone = client.with_options(timeout=1)
            clone.chat.completions.create(model='gpt-4o-mini', messages=[])
            clone.chat.completions.create(model='gpt-4o-mini', messages=[{'role': 'tool', 'tool_call_id': 'call_a', 'content': '{"result":1}'}])
        spans = c.current_run()['spans']
        self.assertEqual(len([s for s in spans if s['type'] == 'llm_call']), 2)
        self.assertEqual(next(s for s in spans if s['type'] == 'tool_call')['output'], '{"result":1}')

    def test_sync_next_and_early_close(self):
        with openai.OpenAI(api_key='test', http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
            stream = client.chat.completions.create(model='gpt-4o-mini', messages=[], stream=True)
            self.assertEqual(next(stream).choices[0].delta.content, 'hello')
            stream.close()
        self.assertEqual(c.current_run()['spans'][0]['status'], 'partial')

    def test_async_stream_context(self):
        async def work():
            async with openai.AsyncOpenAI(api_key='test', http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))) as client:
                stream = await client.with_options(timeout=1).chat.completions.create(model='gpt-4o-mini', messages=[], stream=True)
                chunks = [chunk async for chunk in stream]
                self.assertEqual(len(chunks), 2)
        asyncio.run(work())
        span = c.current_run()['spans'][0]
        self.assertEqual(span['status'], 'completed')
        self.assertIn('hello', str(span['response_content']))

    def test_anthropic_system_and_error(self):
        def handler(request):
            return httpx.Response(200, json={'id': 'm', 'type': 'message', 'role': 'assistant', 'model': 'test', 'content': [{'type': 'tool_use', 'id': 'ta', 'name': 'lookup', 'input': {}}], 'stop_reason': 'tool_use', 'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 2}})
        with anthropic.Anthropic(api_key='test', http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
            client.messages.create(model='test', max_tokens=10, system='Keep original goal', messages=[])
            client.messages.create(model='test', max_tokens=10, messages=[{'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'ta', 'content': 'no permission', 'is_error': True}]}])
        spans = c.current_run()['spans']
        self.assertEqual(spans[0]['system'], 'Keep original goal')
        self.assertTrue(any(s['type'] == 'error' for s in spans))
